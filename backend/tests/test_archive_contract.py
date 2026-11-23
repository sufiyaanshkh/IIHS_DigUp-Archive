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
from app.engine.supervisor import DigUpAdapter, MediaForbidden, MediaNotFound
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
            paths = client.get("/openapi.json").json()["paths"]
        expected = {
            "/api/health": {"get"},
            "/api/engine/status": {"get"},
            "/api/search": {"post"},
            "/api/indexing/status": {"get"},
            "/api/indexing/sync": {"post"},
            "/api/indexing/stop": {"post"},
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

    def test_frontend_archive_client_calls_only_routes_present_in_openapi(self) -> None:
        source = FRONTEND_API.read_text(encoding="utf-8")
        with self.client() as client:
            paths = client.get("/openapi.json").json()["paths"]
        for path in (
            "/api/health", "/api/engine/status", "/api/search", "/api/indexing/status",
            "/api/indexing/sync", "/api/indexing/stop", "/api/media/",
        ):
            self.assertIn(path, source)
        for path in ("/api/health", "/api/engine/status", "/api/search", "/api/indexing/status",
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
                "score": 1.0, "modified": 100, "size": media.stat().st_size,
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
        self.assertEqual(result["hits"][0]["location"], "line 3")
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


if __name__ == "__main__":
    unittest.main()
