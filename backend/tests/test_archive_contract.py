from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.database import connect
from app.auth.authorization import AuthenticatedSession, current_session
from app.auth.sessions import SESSION_COOKIE, create_session
from app.api.routes.archive import router
from app.core.config import Settings
from app.core.engine_config import EngineSettings
from app.engine.supervisor import DigUpAdapter, MediaForbidden, MediaNotFound, SearchProcess
from app.main import create_app
from app.schemas.archive import SearchRequest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API = PROJECT_ROOT / "frontend" / "src" / "lib" / "archive-api.ts"
FRONTEND_TYPES = PROJECT_ROOT / "frontend" / "src" / "lib" / "archive-types.ts"
CLI = PROJECT_ROOT / "backend" / "engine" / "DigUp" / ".build" / "release" / "digup"


class ArchiveContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.workspace = Path(self.tmp.name)
        self.root = self.workspace / "media"
        self.root.mkdir()
        self.index = self.workspace / "index"
        self.auth_db = self.workspace / "auth.sqlite"
        self.settings = Settings(None, None, None, None, 43200, True, "http://testserver")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def client(self, engine=None) -> TestClient:
        engine = engine or EngineSettings(
            executable=self.workspace / "missing-digup",
            index_dir=self.index,
            model_dir=self.workspace / "models",
            roots=(self.root,),
        )
        app = create_app(self.settings, str(self.auth_db), engine_settings=engine)
        return TestClient(app)

    def test_openapi_exposes_archive_and_settings_contracts(self) -> None:
        with self.client() as client:
            specification = client.get("/openapi.json").json()
            paths = specification["paths"]
        expected = {
            "/api/health": {"get"},
            "/api/engine/status": {"get"},
            "/api/engine/prewarm": {"post"},
            "/api/engine/reload": {"post"},
            "/api/search": {"post"},
            "/api/archive": {"get"},
            "/api/indexing/status": {"get"},
            "/api/indexing/sync": {"post"},
            "/api/indexing/stop": {"post"},
            "/api/indexing/backfill": {"post"},
            "/api/media/{handle}": {"get"},
            "/api/media/{handle}/image-metadata": {"get"},
            "/api/media/{handle}/checksum": {"get"},
            "/api/media/{handle}/preview": {"get"},
            "/api/media/{handle}/frame": {"get"},
            "/api/media/{handle}/download": {"get"},
            "/api/media/{handle}/stream": {"get"},
            "/api/settings": {"get"},
            "/api/settings/general": {"get"},
            "/api/settings/folders": {"get"},
            "/api/settings/folders/roots": {"post"},
            "/api/settings/folders/native-roots": {"post"},
            "/api/settings/folders/roots/{root_id}": {"delete"},
            "/api/settings/folders/exclusions": {"post"},
            "/api/settings/folders/exclusions/{exclusion_id}": {"delete"},
            "/api/settings/folders/extensions": {"put"},
            "/api/settings/code": {"get"},
            "/api/settings/code/roots": {"post"},
            "/api/settings/code/roots/{root_id}": {"delete"},
            "/api/settings/code/exclusions": {"post"},
            "/api/settings/code/exclusions/{exclusion_id}": {"delete"},
            "/api/settings/volumes": {"get"},
            "/api/settings/browse": {"get"},
            "/api/settings/storage": {"get"},
            "/api/admin/users": {"get", "post"},
            "/api/admin/users/{user_id}": {"patch"},
            "/api/admin/users/{user_id}/temporary-password": {"post"},
            "/api/admin/audit": {"get"},
            "/api/admin/registration": {"get", "put"},
        }
        self.assertEqual({path: set(ops) for path, ops in paths.items() if path.startswith("/api/")}, expected)
        status = specification["components"]["schemas"]["IndexingStatus"]
        self.assertIn("sync_available", status["required"])
        self.assertEqual(status["properties"]["sync_available"]["type"], "boolean")
        self.assertIn("409", paths["/api/indexing/sync"]["post"]["responses"])

    def test_frontend_archive_client_calls_only_routes_present_in_openapi(self) -> None:
        source = FRONTEND_API.read_text(encoding="utf-8")
        with self.client() as client:
            paths = client.get("/openapi.json").json()["paths"]
        for path in (
            "/api/health", "/api/engine/status", "/api/search", "/api/archive", "/api/indexing/status",
            "/api/indexing/sync", "/api/indexing/stop", "/api/media/",
        ):
            self.assertIn(path, source)
        for path in ("/api/health", "/api/engine/status", "/api/search", "/api/archive", "/api/indexing/status",
                     "/api/indexing/sync", "/api/indexing/stop"):
            self.assertIn(path, paths)
        self.assertIn("/api/media/{handle}", paths)

    def test_search_schema_is_limited_to_original_exposed_modes_and_kinds(self) -> None:
        with self.client() as client:
            schemas = client.get("/openapi.json").json()["components"]["schemas"]
        request = schemas["SearchRequest"]["properties"]
        self.assertEqual(request["mode"]["enum"], ["keyword", "hybrid"])
        self.assertEqual(request["scope"]["enum"], ["archive", "code"])
        self.assertEqual(request["kinds"]["anyOf"][0]["items"]["enum"],
                         ["screenshot", "image", "pdf", "doc", "audio", "video"])
        self.assertNotIn("code", request["kinds"]["anyOf"][0]["items"]["enum"])
        hit_fields = set(schemas["SearchHit"]["properties"])
        frontend_types = FRONTEND_TYPES.read_text(encoding="utf-8")
        def declared_fields(type_name: str) -> set[str]:
            start = frontend_types.index(f"export type {type_name} = {{")
            end = frontend_types.index("};", start)
            block = frontend_types[start:end]
            return {line.strip().split(":", 1)[0] for line in block.splitlines()
                    if ":" in line and not line.lstrip().startswith("//")}

        frontend_hit_fields = declared_fields("SearchHit")
        for field in ("id", "name", "folder", "engine_kind", "segment", "location", "loc", "loc_end",
                      "score", "excerpt", "metadata", "modified", "size", "mime_type", "preview_url",
                      "download_url", "reason"):
            self.assertIn(field, hit_fields)
            self.assertIn(field, frontend_hit_fields)
        self.assertIn('export type SearchMode = "keyword" | "hybrid";', frontend_types)
        response_fields = set(schemas["SearchResponse"]["properties"])
        self.assertTrue(response_fields.issubset(declared_fields("SearchResponse")))

    def test_metadata_response_matches_the_frontend_contract(self) -> None:
        media = self.root / "metadata.txt"
        media.write_text("metadata fixture", encoding="utf-8")
        engine = EngineSettings(
            executable=self.workspace / "missing-digup", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,),
        )
        adapter = DigUpAdapter(engine)
        adapter.search_process.request = AsyncMock(return_value={
            "meaning": False, "strong": 1, "hits": [{
                "path": str(media), "kind": "doc", "segment": "name", "loc": None,
                "loc_end": None, "info": {"pages": "2"}, "excerpt": "metadata fixture",
                "score": 1.0, "keyword_rank": 1, "modified": 100, "size": media.stat().st_size,
            }],
        })
        app = create_app(self.settings, str(self.auth_db), engine_settings=engine, digup=adapter)
        with TestClient(app) as client:
            db = connect(self.auth_db)
            db.execute(
                "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                "VALUES('reader','tenant','reader','reader@iihs.ac.in','Reader','EMPLOYEE','ACTIVE','now','now')"
            )
            cookie = create_session(db, "reader", self.settings)
            db.commit()
            db.close()
            client.cookies.set(SESSION_COOKIE, cookie)
            hit = client.post("/api/search", json={"query": "metadata", "mode": "keyword"}).json()["hits"][0]
            metadata_response = client.get(f"/api/media/{hit['id']}")

        self.assertEqual(hit["reason"], "Has your words")
        self.assertEqual(metadata_response.status_code, 200)
        body = metadata_response.json()
        frontend_types = FRONTEND_TYPES.read_text(encoding="utf-8")
        start = frontend_types.index("export type MediaMetadata = {")
        end = frontend_types.index("};", start)
        frontend_fields = {line.strip().split(":", 1)[0] for line in frontend_types[start:end].splitlines()
                           if ":" in line and not line.lstrip().startswith("//")}
        self.assertEqual(set(body), frontend_fields)
        self.assertEqual(body["metadata"], {"pages": "2"})

    def test_search_request_rejects_modes_and_kinds_not_exposed_by_web_contract(self) -> None:
        for payload in (
            {"query": "archive", "mode": "semantic"},
            {"query": "archive", "kinds": ["code"]},
            {"query": "archive", "limit": 101},
            {"query": "   "},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                SearchRequest.model_validate(payload)

    def test_web_search_modes_map_to_original_jsonl_search_operation(self) -> None:
        media = self.root / "rainfall.txt"
        media.write_text("rainfall archive notes", encoding="utf-8")
        engine = EngineSettings(
            executable=self.workspace / "missing-digup", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,),
        )
        adapter = DigUpAdapter(engine)
        adapter.search_process.request = AsyncMock(return_value={
            "meaning": True,
            "strong": 1,
            "ms": {"search": 3},
            "hits": [{
                "path": str(media), "kind": "doc", "segment": "chunk", "score": 1.25,
                "loc": 0, "loc_end": 0, "excerpt": "rainfall archive notes", "info": {},
                "modified": 10, "size": media.stat().st_size,
            }],
        })

        result = asyncio.run(adapter.search("rainfall", ["doc"], "hybrid", 20, session_id="test-session"))

        kwargs = adapter.search_process.request.await_args.kwargs
        self.assertEqual(adapter.search_process.request.await_args.args, ("search",))
        self.assertEqual(kwargs["q"], "rainfall")
        self.assertEqual(kwargs["kinds"], ["doc"])
        self.assertEqual(kwargs["limit"], 20)
        self.assertIs(kwargs["meaning"], True)
        self.assertIs(kwargs["prefix_last"], False)
        self.assertEqual(result["mode"], "hybrid")
        self.assertEqual(result["hits"][0]["name"], "rainfall.txt")
        self.assertNotIn("path", result["hits"][0])
        self.assertNotIn(str(self.root), str(result))

    def test_match_reasons_follow_desktop_signals_and_segments(self) -> None:
        media = self.root / "fixture"
        media.write_text("synthetic", encoding="utf-8")
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing-digup", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,), code_roots=(self.root,),
        ))
        cases = [
            ({}, "Matches its name"),
            ({"z": None, "keyword_rank": None}, "Matches its name"),
            ({"z": None, "keyword_rank": 0}, "Has your words"),
            ({"z": 1.999999, "keyword_rank": 1, "score": 500}, "Has your words"),
            ({"z": 1.999999}, "Matches its name"),
            ({"z": 2, "keyword_rank": 1, "segment": "image", "kind": "image"}, "Matches the picture"),
            ({"z": 2.001, "segment": "image", "kind": "screenshot"}, "Matches what's on screen"),
            ({"z": 2, "segment": "ocr"}, "Matches the text in it"),
            ({"z": 2, "segment": "frame", "loc": 65.9}, "Matches the frame at 1:05"),
            ({"z": 2, "segment": "frame", "loc": 3661}, "Matches the frame at 1:01:01"),
            ({"z": 2, "segment": "frame"}, "Matches the frame at "),
            ({"z": 2, "segment": "audio", "kind": "video", "loc": 6}, "Matches the sound at 0:06"),
            ({"z": 2, "segment": "audio", "kind": "audio", "loc": 6}, "Matches what's heard at 0:06"),
            ({"z": 2, "segment": "audio"}, "Matches what's heard at "),
            ({"z": 2, "segment": "page", "loc": 3.9}, "Matches the text on page 3"),
            ({"z": 2, "segment": "page"}, "Matches the text on a page"),
            ({"z": 2, "segment": "page_image", "loc": 3}, "Matches page 3"),
            ({"z": 2, "segment": "page_image"}, "Matches a page"),
            ({"z": 2, "segment": "chunk"}, "Matches its text"),
            ({"z": 2, "segment": "name"}, "Matches its name"),
            ({"z": 2, "segment": "unknown"}, "Matches its name"),
            ({"z": 2, "segment": "lines", "kind": "code", "loc": 12}, "Matches line 12"),
            ({"z": 2, "segment": "lines", "kind": "code", "loc": 12, "loc_end": 40}, "Matches lines 12–40"),
            ({"z": 2, "segment": "cells", "kind": "code", "loc": 3}, "Matches cell 3"),
            ({"z": 2, "segment": "cells", "kind": "code", "loc": 3, "loc_end": 5}, "Matches cells 3–5"),
            ({"z": 2, "segment": "lines", "kind": "code"}, "Matches the code"),
            ({"z": 2, "segment": "cells", "kind": "code"}, "Matches the code"),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                raw = {"path": str(media), "kind": "doc", "segment": "name", **fields}
                hit = adapter._register_hit(raw, "test-session", code=raw["kind"] == "code")
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit["reason"], expected)

    def test_keyword_mode_disables_meaning_in_original_protocol(self) -> None:
        engine = EngineSettings(
            executable=self.workspace / "missing-digup", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,),
        )
        adapter = DigUpAdapter(engine)
        adapter.search_process.request = AsyncMock(return_value={"meaning": False, "strong": 0, "hits": []})

        result = asyncio.run(adapter.search("invoice number", None, "keyword", 10, session_id="test-session"))

        self.assertIs(adapter.search_process.request.await_args.kwargs["meaning"], False)
        self.assertEqual(result["mode"], "keyword")
        self.assertEqual(result["hits"], [])

    def test_prefix_search_uses_original_protocol_without_changing_other_options(self) -> None:
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,),
        ))
        adapter.search_process.request = AsyncMock(return_value={"meaning": False, "strong": 0, "hits": []})
        asyncio.run(adapter.search("cat", ["doc"], "keyword", 20, session_id="test", prefix_last=True))
        kwargs = adapter.search_process.request.await_args.kwargs
        self.assertEqual((kwargs["q"], kwargs["kinds"], kwargs["limit"]), ("cat", ["doc"], 20))
        self.assertIs(kwargs["meaning"], False)
        self.assertIs(kwargs["prefix_last"], True)
        self.assertFalse(SearchRequest(query="cat").prefix_last)
        with self.assertRaises(ValidationError):
            SearchRequest(query="cat", prefix_last="true")

    def test_cancelled_helper_request_clears_its_pending_future(self) -> None:
        async def exercise() -> None:
            process = SearchProcess(EngineSettings(
                executable=self.workspace / "missing", index_dir=self.index,
                model_dir=self.workspace / "models", roots=(self.root,),
            ))
            class Input:
                def write(self, data: bytes) -> None:
                    pass
                async def drain(self) -> None:
                    pass
            class Child:
                stdin = Input()
            process.process = Child()
            process._start = AsyncMock()
            task = asyncio.create_task(process.request("search", q="cat"))
            await asyncio.sleep(0)
            self.assertEqual(len(process._pending), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(process._pending, {})
        asyncio.run(exercise())

    def test_strong_boundary_tracks_only_retained_original_strong_hits(self) -> None:
        strong = self.root / "strong.txt"
        weak = self.root / "weak.txt"
        excluded = self.root / "excluded.txt"
        for path in (strong, weak, excluded):
            path.write_text("synthetic", encoding="utf-8")
        engine = EngineSettings(
            executable=self.workspace / "missing-digup", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,),
            excluded_folders=(excluded,),
        )
        adapter = DigUpAdapter(engine)
        adapter.search_process.request = AsyncMock(return_value={
            "meaning": True, "strong": 3,
            "hits": [
                {"path": str(self.workspace / "missing.txt"), "kind": "doc"},
                {"path": str(strong), "kind": "doc"},
                {"path": str(excluded), "kind": "doc"},
                {"path": str(weak), "kind": "doc"},
            ],
        })

        result = asyncio.run(adapter.search("synthetic", None, "hybrid", 10, session_id="test"))

        self.assertEqual([hit["name"] for hit in result["hits"]], ["strong.txt", "weak.txt"])
        self.assertEqual(result["strong"], 1)
        self.assertEqual(result["total"], 2)

        adapter.search_process.request.return_value["strong"] = 1
        result = asyncio.run(adapter.search("synthetic", None, "hybrid", 10, session_id="test"))
        self.assertEqual(result["strong"], 0)
        self.assertEqual(result["total"], 2)

    @unittest.skipUnless(CLI.is_file(), "the original DigUp CLI is not built")
    def test_real_engine_prefix_and_hybrid_fallback_use_disposable_index(self) -> None:
        models = self.workspace / "models"
        models.mkdir()
        env = {**os.environ, "HOME": str(self.workspace), "TMPDIR": str(self.workspace), "DIGUP_MODELS": str(models)}
        subprocess.run(
            [str(CLI), "search-service", "--index", str(self.index), str(self.root)],
            input='{"id":"quit","op":"quit"}\n', capture_output=True, text=True, env=env, timeout=30, check=True,
        )
        files = [self.root / "cat.txt", self.root / "category.txt"]
        for file in files:
            file.write_text("synthetic", encoding="utf-8")
        with closing(sqlite3.connect(self.index / "index.sqlite")) as db:
            for identifier, file in enumerate(files, 1):
                stat = file.stat()
                db.execute(
                    "INSERT INTO files(id,path,kind,size,mtime,inode,device,state,info) VALUES(?,?,?,?,?,?,?,?,?)",
                    (identifier, str(file), "doc", stat.st_size, stat.st_mtime, stat.st_ino, stat.st_dev, "done", "{}"),
                )
                db.execute("INSERT INTO segments(id,file,kind,modality) VALUES(?,?,'name','none')",
                           (identifier, identifier))
                db.execute("INSERT INTO fts(rowid,name,body) VALUES(?,?,?)",
                           (identifier, file.stem, file.stem))
            db.execute("INSERT INTO segments(id,file,kind,modality) VALUES(3,1,'chunk','none')")
            db.execute("INSERT INTO fts(rowid,name,body) VALUES(3,'cat','cat')")
            db.commit()
        adapter = DigUpAdapter(EngineSettings(executable=CLI, index_dir=self.index, model_dir=models, roots=(self.root,)))
        async def exercise() -> None:
            try:
                prefix = await adapter.search("cat", ["doc"], "keyword", 20, session_id="test", prefix_last=True)
                final = await adapter.search("cat", ["doc"], "keyword", 20, session_id="test")
                hybrid = await adapter.search("cat", ["doc"], "hybrid", 20, session_id="test")
                self.assertEqual({hit["name"] for hit in prefix["hits"]}, {"cat.txt", "category.txt"})
                self.assertEqual([hit["name"] for hit in final["hits"]], ["cat.txt"])
                self.assertEqual([hit["name"] for hit in hybrid["hits"]], ["cat.txt"])
                self.assertTrue(all(hit["reason"] == "Has your words" for hit in prefix["hits"]))
                self.assertEqual(final["hits"][0]["reason"], "Has your words")
                self.assertEqual(hybrid["hits"][0]["reason"], "Has your words")
                self.assertFalse(hybrid["meaning"])
                self.assertEqual(len(prefix["hits"]), 2)
                self.assertLessEqual(prefix["strong"], prefix["total"])
            finally:
                await adapter.close()
        with patch.dict(os.environ, {"HOME": str(self.workspace), "TMPDIR": str(self.workspace)}):
            asyncio.run(exercise())
            app = create_app(self.settings, str(self.auth_db), engine_settings=EngineSettings(
                executable=CLI, index_dir=self.index, model_dir=models, roots=(self.root,),
            ))
            with TestClient(app) as client:
                db = connect(self.auth_db)
                db.execute(
                    "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                    "VALUES('reader','tenant','reader','reader@iihs.ac.in','Reader','EMPLOYEE','ACTIVE','now','now')"
                )
                cookie = create_session(db, "reader", self.settings)
                db.commit()
                db.close()
                client.cookies.set(SESSION_COOKIE, cookie)
                response = client.post("/api/search", json={"query": "cat", "mode": "keyword"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([(hit["name"], hit["reason"]) for hit in response.json()["hits"]],
                                 [("cat.txt", "Has your words")])

    @unittest.skipUnless(CLI.is_file(), "the original DigUp CLI is not built")
    def test_kind_filter_is_applied_by_original_engine_before_limit(self) -> None:
        models = self.workspace / "models"
        models.mkdir()
        document = self.root / "saffron.txt"
        audio = self.root / "saffron.mp3"
        document.write_text("synthetic saffron document", encoding="utf-8")
        audio.write_bytes(b"synthetic audio")
        env = {**os.environ, "HOME": str(self.workspace), "TMPDIR": str(self.workspace),
               "DIGUP_MODELS": str(models)}
        boot = subprocess.run(
            [str(CLI), "search-service", "--index", str(self.index), str(self.root)],
            input='{"id":"quit","op":"quit"}\n', capture_output=True, text=True,
            env=env, timeout=30, check=True,
        )
        self.assertTrue(any(json.loads(line).get("event") == "ready" for line in boot.stdout.splitlines()))
        with closing(sqlite3.connect(self.index / "index.sqlite")) as db:
            for identifier, (file, kind) in enumerate(((document, "doc"), (audio, "audio")), 1):
                stat = file.stat()
                db.execute(
                    "INSERT INTO files(id,path,kind,size,mtime,inode,device,state,info) VALUES(?,?,?,?,?,?,?,?,?)",
                    (identifier, str(file), kind, stat.st_size, stat.st_mtime, stat.st_ino, stat.st_dev, "done", "{}"),
                )
                db.execute(
                    "INSERT INTO segments(id,file,kind,modality) VALUES(?,?,'name','none')",
                    (identifier, identifier),
                )
                db.execute("INSERT INTO fts(rowid,name,body) VALUES(?,?,?)",
                           (identifier, file.name, "saffron"))
            db.commit()
        adapter = DigUpAdapter(EngineSettings(
            executable=CLI, index_dir=self.index, model_dir=models, roots=(self.root,),
        ))

        async def search() -> None:
            try:
                unfiltered = await adapter.search("saffron", None, "keyword", 1, session_id="test")
                filtered = await adapter.search("saffron", ["audio"], "keyword", 1, session_id="test")
                self.assertEqual([hit["name"] for hit in unfiltered["hits"]], [document.name])
                self.assertEqual([hit["name"] for hit in filtered["hits"]], [audio.name])
            finally:
                await adapter.close()

        with patch.dict(os.environ, {"HOME": str(self.workspace), "TMPDIR": str(self.workspace)}):
            asyncio.run(search())

    def test_media_handles_are_bound_to_the_issuing_session(self) -> None:
        media = self.root / "photo.jpg"
        media.write_bytes(b"disposable image placeholder")
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing-digup", index_dir=self.index,
            model_dir=self.workspace / "models", roots=(self.root,),
        ))
        result = adapter._register_hit({"path": str(media), "kind": "image", "info": {}}, "session-one")
        self.assertIsNotNone(result)
        handle = result["id"]
        with self.assertRaises(MediaNotFound):
            adapter.media(handle, session_id="session-two")
        self.assertEqual(adapter.media(handle, session_id="session-one").path, media.resolve())

    def test_code_search_scopes_hits_and_revokes_removed_or_excluded_roots(self) -> None:
        code_root = self.workspace / "code"
        excluded = code_root / "private"
        excluded.mkdir(parents=True)
        project = code_root / "project"
        project.mkdir()
        code = project / "example.py"
        code.write_text("def example(): pass", encoding="utf-8")
        secret = excluded / "secret.py"
        secret.write_text("not visible", encoding="utf-8")
        outsider = self.root / "outside.py"
        outsider.write_text("not a code root", encoding="utf-8")
        escape = code_root / "escape.py"
        escape.symlink_to(outsider)
        excluded_alias = code_root / "excluded-alias.py"
        excluded_alias.symlink_to(secret)
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing", index_dir=self.index, model_dir=self.workspace / "models",
            roots=(self.root,), code_roots=(self.workspace / "missing-root", code_root),
            code_excluded_folders=(excluded,),
        ))
        def hit(path: Path) -> dict:
            return {"path": str(path), "kind": "code", "segment": "lines", "segment_id": 42,
                    "loc": 3, "loc_end": 4, "info": {}, "score": 1.0, "modified": 1, "size": 1}
        adapter.search_process.request = AsyncMock(return_value={
            "meaning": False, "strong": 1,
            "hits": [hit(code), hit(secret), hit(outsider), hit(escape), hit(excluded_alias)],
        })
        result = asyncio.run(adapter.search("example", None, "keyword", 10, session_id="owner", code=True))
        self.assertTrue(adapter.search_process.request.await_args.kwargs["code"])
        self.assertEqual([row["name"] for row in result["hits"]], ["example.py"])
        self.assertEqual(result["hits"][0]["location"], "lines 3–4")
        for segment, end, expected in (("lines", 3, "line 3"), ("cells", 5, "cells 3–5"),
                                       ("cells", None, "cell 3")):
            with self.subTest(segment=segment, end=end):
                source_hit = {**hit(code), "segment": segment, "loc_end": end}
                self.assertEqual(adapter._register_hit(source_hit, "owner", code=True)["location"], expected)
        self.assertNotIn(str(code_root), str(result))
        handle = result["hits"][0]["id"]
        with self.assertRaises(MediaNotFound):
            adapter.media(handle, session_id="other")
        adapter.settings = replace(adapter.settings, code_excluded_folders=(project,))
        with self.assertRaises(MediaForbidden):
            adapter.media(handle, session_id="owner")
        adapter.settings = replace(adapter.settings, code_roots=(code_root, project))
        with self.assertRaises(MediaForbidden):
            adapter.media(handle, session_id="owner")
        refreshed = adapter._register_hit(hit(code), "owner", code=True)
        self.assertEqual(adapter.media(refreshed["id"], session_id="owner").path, code.resolve())
        adapter.settings = replace(adapter.settings, code_roots=(), code_excluded_folders=())
        with self.assertRaises(MediaForbidden):
            adapter.media(handle, session_id="owner")

    def test_code_search_requires_operator_and_issuing_session(self) -> None:
        code = self.workspace / "example.py"
        code.write_text("def example(): pass", encoding="utf-8")
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing", index_dir=self.index, model_dir=self.workspace / "models",
            roots=(), code_roots=(self.workspace,),
        ))
        async def original(operation: str, **fields):
            if operation == "search":
                return {"meaning": False, "strong": 1, "hits": [{
                    "path": str(code), "kind": "code", "segment": "lines", "segment_id": 42,
                    "loc": 1, "info": {}, "score": 1.0, "modified": 1, "size": 19,
                }]}
            raise AssertionError(operation)
        adapter.search_process.request = AsyncMock(side_effect=original)
        app = FastAPI()
        app.include_router(router)
        app.state.digup = adapter
        def session(request: Request) -> AuthenticatedSession:
            identity = request.headers.get("x-test-session")
            if not identity:
                raise HTTPException(status_code=401)
            return AuthenticatedSession(identity, identity, request.headers["x-test-role"], "", "", "", False)
        app.dependency_overrides[current_session] = session
        operator = {"x-test-session": "owner", "x-test-role": "ARCHIVE_OPERATOR"}
        employee = {"x-test-session": "owner", "x-test-role": "EMPLOYEE"}
        other = {"x-test-session": "other", "x-test-role": "ADMIN"}
        with TestClient(app) as client:
            payload = {"query": "example", "mode": "keyword", "scope": "code"}
            self.assertEqual(client.post("/api/search", json=payload).status_code, 401)
            self.assertEqual(client.post("/api/search", json=payload, headers=employee).status_code, 403)
            self.assertEqual(client.post("/api/search", json={**payload, "kinds": ["doc"]}, headers=operator).status_code, 422)
            response = client.post("/api/search", json=payload, headers=operator)
            self.assertEqual(response.status_code, 200, response.text)
            handle = response.json()["hits"][0]["id"]
            url = f"/api/media/{handle}"
            self.assertEqual(client.get(url, headers=employee).status_code, 403)
            self.assertEqual(client.get(url, headers=other).status_code, 404)
            self.assertEqual(client.get(url, headers=operator).status_code, 200)
            self.assertEqual(client.get(f"/api/media/{handle}/download", headers=employee).status_code, 403)

    def test_media_stream_supports_ranges_and_is_session_bound(self) -> None:
        video = self.root / "sample.mp4"
        video.write_bytes(b"synthetic-video-data")
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing", index_dir=self.index, model_dir=self.workspace / "models",
            roots=(self.root,),
        ))
        hit = adapter._register_hit({"path": str(video), "kind": "video", "info": {}}, "owner")
        self.assertIsNotNone(hit)
        app = FastAPI()
        app.include_router(router)
        app.state.digup = adapter
        def session(request: Request) -> AuthenticatedSession:
            identity = request.headers.get("x-test-session")
            if not identity:
                raise HTTPException(status_code=401)
            return AuthenticatedSession(identity, identity, "EMPLOYEE", "", "", "", False)
        app.dependency_overrides[current_session] = session
        url = f"/api/media/{hit['id']}/stream"
        with TestClient(app) as client:
            self.assertEqual(client.get(url).status_code, 401)
            self.assertEqual(client.get(url, headers={"x-test-session": "other"}).status_code, 404)
            response = client.get(url, headers={"x-test-session": "owner", "range": "bytes=0-8"})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, b"synthetic")
            self.assertEqual(response.headers["content-type"], "video/mp4")
            self.assertEqual(response.headers["cache-control"], "private, no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(client.get(url, headers={"x-test-session": "owner", "range": "bytes=999-"}).status_code, 416)
            adapter.settings = replace(adapter.settings, excluded_extensions=("mp4",))
            self.assertEqual(client.get(url, headers={"x-test-session": "owner"}).status_code, 403)
            adapter.settings = replace(adapter.settings, excluded_extensions=(), roots=())
            self.assertEqual(client.get(url, headers={"x-test-session": "owner"}).status_code, 403)
            adapter.settings = replace(adapter.settings, roots=(self.root,))
            image = adapter._register_hit({"path": str(video), "kind": "image", "info": {}}, "owner")
            self.assertEqual(client.get(f"/api/media/{image['id']}/stream",
                                        headers={"x-test-session": "owner"}).status_code, 415)
            audio = self.root / "sample.mp3"
            audio.write_bytes(b"synthetic-audio-data")
            audio_hit = adapter._register_hit({"path": str(audio), "kind": "audio", "info": {}}, "owner")
            response = client.get(f"/api/media/{audio_hit['id']}/stream",
                                  headers={"x-test-session": "owner", "range": "bytes=0-8"})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, b"synthetic")
            self.assertEqual(response.headers["content-type"], "audio/mpeg")

    def test_pdf_pages_and_video_frames_use_original_render_operation(self) -> None:
        pdf = self.root / "sample.pdf"
        video = self.root / "sample.mp4"
        pdf.write_bytes(b"synthetic pdf")
        video.write_bytes(b"synthetic video")
        previews = self.index / "previews"
        previews.mkdir(parents=True)
        image = previews / "preview.jpg"
        image.write_bytes(b"synthetic preview")
        adapter = DigUpAdapter(EngineSettings(
            executable=self.workspace / "missing", index_dir=self.index, model_dir=self.workspace / "models",
            roots=(self.root,),
        ))
        adapter.search_process.request = AsyncMock(return_value={"image": str(image)})
        pdf_hit = adapter._register_hit({"path": str(pdf), "kind": "pdf", "info": {"pages": "3"}}, "owner")
        video_hit = adapter._register_hit({"path": str(video), "kind": "video", "info": {"duration": "10"}}, "owner")

        async def verify() -> None:
            self.assertEqual(await adapter.render(pdf_hit["id"], at=2, pixels=512, session_id="owner"), image)
            self.assertEqual(adapter.search_process.request.await_args.kwargs["kind"], "pdf")
            self.assertEqual(adapter.search_process.request.await_args.kwargs["loc"], 2)
            self.assertEqual(await adapter.render(video_hit["id"], at=7.5, pixels=512,
                                                  session_id="owner", frame_only=True), image)
            self.assertEqual(adapter.search_process.request.await_args.kwargs["kind"], "video")
            self.assertEqual(adapter.search_process.request.await_args.kwargs["loc"], 7.5)
            with self.assertRaises(ValueError):
                await adapter.render(pdf_hit["id"], at=4, pixels=512, session_id="owner")
            with self.assertRaises(ValueError):
                await adapter.render(video_hit["id"], at=11, pixels=512, session_id="owner", frame_only=True)
            with self.assertRaises(MediaNotFound):
                await adapter.render(video_hit["id"], at=1, pixels=512, session_id="other", frame_only=True)

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()
