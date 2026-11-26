from __future__ import annotations

import concurrent.futures
from dataclasses import replace
import json
import os
import sqlite3
import struct
import subprocess
import tempfile
import unittest
import zlib
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.engine_config import EngineSettings
from app.auth.database import connect
from app.auth.sessions import SESSION_COOKIE, create_session
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = PROJECT_ROOT / "backend" / "engine" / "DigUp"
CLI = ENGINE_ROOT / ".build" / "release" / "digup"


def _png(path: Path, width: int = 320, height: int = 240) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend((210, 60, 40) if x < width // 2 else (40, 80, 190))
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))
    path.write_bytes(data)


@unittest.skipUnless(CLI.is_file(), "the pinned DigUp CLI is required")
class ArchiveApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.workspace = Path(self.tmp.name)
        self.root = self.workspace / "media"
        self.root.mkdir()
        self.index = self.workspace / "index"
        self.auth_db = self.workspace / "auth.sqlite"
        self.models = self.workspace / "empty-models"
        self.models.mkdir()
        (self.root / "rainfall-notes.txt").write_text(
            "The saffron observatory records monsoon rainfall across the western district.\n", encoding="utf-8"
        )
        (self.root / "coastal-survey.txt").write_text(
            "A copper migration survey follows coastal households from 1984.\n", encoding="utf-8"
        )
        (self.root / "harbor-log.txt").write_text(
            "The lighthouse keeper recorded a severe storm warning near the northern harbor.\n", encoding="utf-8"
        )
        (self.root / "reports").mkdir()
        (self.root / "reports" / "quarterly.txt").write_text(
            "A synthetic quarterly archive report for folder browsing.\n", encoding="utf-8"
        )
        (self.root / "reports" / "nested").mkdir()
        (self.root / "reports" / "nested" / "field-notes.odt").write_bytes(b"synthetic document")
        _png(self.root / "reports" / "nested" / "nested-image.webp")
        (self.root / "empty-folder").mkdir()
        (self.root / "field-recording.wav").write_bytes(b"synthetic audio")
        (self.root / "unindexed-video.mp4").write_bytes(b"synthetic video")
        (self.root / "unindexed-report.pdf").write_bytes(b"synthetic pdf")
        (self.root / "unindexed-markdown.md").write_text("not in the DigUp index", encoding="utf-8")
        try:
            (self.root / "outside-link").symlink_to(self.workspace, target_is_directory=True)
        except OSError:
            pass
        _png(self.root / "color-study.png")
        (self.root / "Screenshot 2026.png").write_bytes((self.root / "color-study.png").read_bytes())
        self.ffmpeg = __import__("shutil").which("ffmpeg")
        if self.ffmpeg:
            subprocess.run([
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=white:s=640x480:r=24:d=6",
                "-vf", "drawbox=x=0:y=0:w=320:h=480:color=red:t=fill:enable='lt(t,3)',"
                       "drawbox=x=320:y=0:w=320:h=480:color=blue:t=fill:enable='gte(t,3)'",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.root / "sequence.mov"),
            ], check=True)
        self.engine_settings = EngineSettings(
            executable=CLI.resolve(), index_dir=self.index.resolve(), model_dir=self.models.resolve(),
            roots=(self.root.resolve(), (self.workspace / "disconnected-drive").resolve()),
            excluded_extensions=("md",), request_timeout_seconds=60,
        )
        self.settings = Settings(None, None, None, None, 43200, True, "https://testserver")
        self.environment = patch.dict(os.environ, {"HOME": str(self.workspace), "TMPDIR": str(self.workspace)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self._seed_index()
        self.app = create_app(self.settings, str(self.auth_db), engine_settings=self.engine_settings)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_index(self) -> None:
        boot = subprocess.run(
            [str(CLI), "search-service", "--index", str(self.index), str(self.root)],
            input='{"id":"quit","op":"quit"}\n', capture_output=True, text=True,
            env=self.engine_settings.process_environment(), timeout=30, check=True,
        )
        self.assertTrue(any(json.loads(line).get("event") == "ready" for line in boot.stdout.splitlines()))
        entries = [
            ("rainfall-notes.txt", "doc", "the saffron observatory records monsoon rainfall across the western district"),
            ("coastal-survey.txt", "doc", "a copper migration survey follows coastal households"),
            ("harbor-log.txt", "doc", "the lighthouse keeper recorded a storm warning"),
            ("reports/quarterly.txt", "doc", "a synthetic quarterly archive report for folder browsing"),
            ("color-study.png", "image", ""),
        ]
        if self.ffmpeg:
            entries.append(("sequence.mov", "video", ""))
        with closing(sqlite3.connect(self.index / "index.sqlite")) as db, db:
            for identifier, (name, kind, body) in enumerate(entries, 1):
                path = self.root / name
                info = path.stat()
                db.execute(
                    "INSERT INTO files(id,path,kind,size,mtime,inode,device,state,info) VALUES(?,?,?,?,?,?,?,?,?)",
                    (identifier, str(path), kind, info.st_size, info.st_mtime, info.st_ino, info.st_dev, "done", "{}"),
                )
                db.execute("INSERT INTO segments(id,file,kind,modality) VALUES(?,?,?,'none')",
                           (identifier, identifier, "chunk" if kind == "doc" else "name"))
                db.execute("INSERT INTO fts(rowid,name,body) VALUES(?,?,?)", (identifier, name, body))

    def test_search_preview_metadata_download_concurrency_and_restart(self) -> None:
        with TestClient(self.app, base_url="https://testserver") as client:
            db = connect(self.auth_db)
            db.execute(
                "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                "VALUES('operator','tenant','operator','operator@iihs.ac.in','Operator','ARCHIVE_OPERATOR','ACTIVE','now','now')"
            )
            session_cookie = create_session(db, "operator", self.settings)
            db.commit()
            db.close()
            client.cookies.set(SESSION_COOKIE, session_cookie)
            csrf = client.get("/auth/session").headers["x-csrf-token"]
            health = client.get("/api/health").json()
            self.assertTrue(health["digup_cli_available"])
            self.assertFalse(health["models_available"])
            self.assertEqual(client.get("/api/engine/status").status_code, 200)
            self.assertEqual(client.post("/api/indexing/sync", headers={
                "origin": "https://testserver", "x-csrf-token": csrf,
            }).status_code, 409)
            status = client.get("/api/indexing/status").json()
            self.assertFalse(status["sync_available"])
            self.assertTrue(status["summary_available"])
            self.assertGreaterEqual(status["roots"][0]["files"], 5 if self.ffmpeg else 4)
            self.assertFalse(any("/" in str(event.get("path", "")) for event in status["events"]))

            sources = client.get("/api/archive")
            self.assertEqual(sources.status_code, 200, sources.text)
            source = sources.json()["sources"][0]
            self.assertNotIn(str(self.root), sources.text)
            root_listing = client.get("/api/archive", params={"source_id": source["id"], "limit": 2})
            self.assertEqual(root_listing.status_code, 200, root_listing.text)
            self.assertEqual(root_listing.json()["schema_version"], 5)
            self.assertEqual(root_listing.json()["total"], 12 if self.ffmpeg is False else 13)
            self.assertEqual(len(root_listing.json()["items"]), 2)
            root_folders = {item["name"]: item for item in root_listing.json()["folders"]}
            self.assertEqual(root_folders["reports"]["file_count"], 3)
            self.assertEqual(root_folders["empty-folder"]["file_count"], 0)
            next_page = client.get("/api/archive", params={"source_id": source["id"], "offset": 2, "limit": 2})
            self.assertEqual(next_page.status_code, 200, next_page.text)
            self.assertFalse({item["relative_path"] for item in root_listing.json()["items"]} &
                             {item["relative_path"] for item in next_page.json()["items"]})
            image_listing = client.get("/api/archive", params={
                "source_id": source["id"], "media_type": "image",
            })
            self.assertEqual({item["name"] for item in image_listing.json()["items"]}, {"color-study.png", "nested-image.webp"})
            for media_type, expected in (("screenshot", "Screenshot 2026.png"), ("video", "unindexed-video.mp4"),
                                         ("audio", "field-recording.wav"), ("document", "unindexed-report.pdf")):
                listing = client.get("/api/archive", params={"source_id": source["id"], "media_type": media_type})
                self.assertIn(expected, {item["name"] for item in listing.json()["items"]})
            unindexed = client.get("/api/archive", params={"source_id": source["id"], "state": "unindexed"})
            self.assertGreaterEqual(unindexed.json()["total"], 7)
            all_files = client.get("/api/archive", params={"source_id": source["id"], "limit": 100}).json()
            self.assertIn("rainfall-notes.txt", {item["name"] for item in all_files["items"]})
            markdown = next(item for item in all_files["items"] if item["name"] == "unindexed-markdown.md")
            self.assertEqual(markdown["processing_state"], "unindexed")
            self.assertEqual(client.get(markdown["download_url"]).content, b"not in the DigUp index")
            self.assertIn("reports/nested/nested-image.webp", {item["relative_path"] for item in all_files["items"]})
            adapter = self.app.state.digup
            indexed_settings = adapter.settings
            try:
                adapter.settings = replace(indexed_settings, index_dir=self.workspace / "missing-index")
                unknown_status = client.get("/api/archive", params={"source_id": source["id"], "limit": 100}).json()
            finally:
                adapter.settings = indexed_settings
            self.assertTrue(all(item["processing_state"] == "unknown" for item in unknown_status["items"]))
            folder_listing = client.get("/api/archive", params={
                "source_id": source["id"], "folder": "reports",
            })
            self.assertEqual(folder_listing.status_code, 200, folder_listing.text)
            self.assertEqual([item["name"] for item in folder_listing.json()["items"]], ["quarterly.txt"])
            self.assertEqual([item["name"] for item in client.get("/api/archive", params={
                "source_id": source["id"], "folder": "reports/nested",
            }).json()["items"]], ["field-notes.odt", "nested-image.webp"])
            empty_listing = client.get("/api/archive", params={"source_id": source["id"], "folder": "empty-folder"})
            self.assertEqual(empty_listing.status_code, 200)
            self.assertEqual(empty_listing.json()["total"], 0)
            self.assertEqual(client.get("/api/archive", params={
                "source_id": source["id"], "folder": "../",
            }).status_code, 422)
            if (self.root / "outside-link").is_symlink():
                self.assertEqual(client.get("/api/archive", params={
                    "source_id": source["id"], "folder": "outside-link",
                }).status_code, 404)
            client.cookies.clear()
            self.assertEqual(client.get("/api/archive", params={"source_id": source["id"]}).status_code, 401)
            client.cookies.set(SESSION_COOKIE, session_cookie)

            keyword = client.post("/api/search", json={
                "query": "monsoon rainfall", "mode": "keyword", "limit": 10,
            })
            self.assertEqual(keyword.status_code, 200, keyword.text)
            self.assertFalse(keyword.json()["meaning"])
            self.assertEqual(keyword.json()["hits"][0]["name"], "rainfall-notes.txt")

            prefix = client.post("/api/search", json={
                "query": "mon", "mode": "keyword", "prefix_last": True, "kinds": ["doc"], "limit": 1,
            })
            self.assertEqual(prefix.status_code, 200, prefix.text)
            self.assertEqual([hit["name"] for hit in prefix.json()["hits"]], ["rainfall-notes.txt"])

            hybrid = client.post("/api/search", json={
                "query": "rainfall records from the western district in the wet season",
                "mode": "hybrid", "limit": 10,
            })
            self.assertEqual(hybrid.status_code, 200, hybrid.text)
            self.assertFalse(hybrid.json()["meaning"])
            self.assertEqual(hybrid.json()["hits"][0]["name"], "rainfall-notes.txt")

            document = self.root / "rainfall-notes.txt"
            semantic_document = self.root / "coastal-survey.txt"
            synthetic_response = {
                "meaning": True, "strong": 1, "ms": {"embed": 1, "search": 2},
                "hits": [{"path": str(document), "kind": "doc", "segment": "chunk",
                          "score": 2.5, "loc": 0, "loc_end": 0, "excerpt": "rainfall",
                          "info": {}, "modified": document.stat().st_mtime, "size": document.stat().st_size},
                         {"path": str(semantic_document), "kind": "doc", "segment": "chunk",
                          "score": 0.75, "loc": 0, "loc_end": 0, "excerpt": "coastal",
                          "info": {}, "modified": semantic_document.stat().st_mtime,
                          "size": semantic_document.stat().st_size}],
            }
            with patch.object(self.app.state.digup.search_process, "request",
                              new=AsyncMock(return_value=synthetic_response)) as request:
                semantic = client.post("/api/search", json={"query": "rainfall", "mode": "hybrid", "limit": 7})
                self.assertEqual(semantic.status_code, 200, semantic.text)
                self.assertTrue(semantic.json()["meaning"])
                self.assertEqual(semantic.json()["hits"][0]["name"], document.name)
                self.assertEqual(semantic.json()["hits"][0]["score"], 2.5)
                self.assertEqual([hit["name"] for hit in semantic.json()["hits"]],
                                 [document.name, semantic_document.name])
                self.assertEqual(semantic.json()["strong"], 1)
                self.assertEqual(request.await_args.args, ("search",))
                self.assertTrue(request.await_args.kwargs["meaning"])
                self.assertEqual(request.await_args.kwargs["limit"], 7)

            by_image_name = client.post("/api/search", json={
                "query": "color-study.png", "mode": "keyword", "kinds": ["image"],
            }).json()["hits"]
            image_hit = next(hit for hit in by_image_name if hit["name"] == "color-study.png")
            metadata = client.get(f"/api/media/{image_hit['id']}")
            self.assertEqual(metadata.status_code, 200)
            image_metadata = client.get(f"/api/media/{image_hit['id']}/image-metadata")
            self.assertEqual(image_metadata.status_code, 200, image_metadata.text)
            self.assertEqual(set(image_metadata.json()), {
                "camera", "lens", "aperture", "iso", "shutter_speed", "white_balance",
                "exposure_compensation", "location", "capture_time", "dimensions",
            })
            self.assertNotIn(str(self.root), image_metadata.text)
            image_preview = client.get(image_hit["preview_url"])
            self.assertEqual(image_preview.status_code, 200)
            self.assertEqual(image_preview.headers["content-type"], "image/jpeg")

            download = client.get(image_hit["download_url"])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.content[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(client.get("/api/media/not-a-handle").status_code, 404)
            moved_root = self.root.with_name("media-unavailable")
            self.root.rename(moved_root)
            try:
                unavailable = client.get("/api/archive", params={"source_id": source["id"]})
                self.assertEqual(unavailable.status_code, 503)
            finally:
                moved_root.rename(self.root)
            self.assertEqual(client.post("/api/search", json={"query": "   "}).status_code, 422)

            if self.ffmpeg:
                video_hits = client.post("/api/search", json={
                    "query": "sequence.mov", "mode": "keyword", "kinds": ["video"],
                }).json()["hits"]
                video_hit = next(hit for hit in video_hits if hit["name"] == "sequence.mov")
                cached_frame = self.index / "previews" / "test-frame.jpg"
                cached_frame.write_bytes(image_preview.content)
                with patch.object(self.app.state.digup.search_process, "request",
                                  new=AsyncMock(return_value={"image": str(cached_frame)})) as render:
                    frame = client.get(f"/api/media/{video_hit['id']}/frame?at=3.5")
                    render.assert_awaited_once_with(
                        "render", path=str(self.root / "sequence.mov"), kind="video", loc=3.5, pixels=1024,
                    )
                self.assertEqual(frame.status_code, 200, frame.text)
                self.assertEqual(frame.headers["content-type"], "image/jpeg")
                stream = client.get(f"/api/media/{video_hit['id']}/stream", headers={"range": "bytes=0-15"})
                self.assertEqual(stream.status_code, 206)
                self.assertEqual(len(stream.content), 16)

            def concurrent_search(_: int) -> int:
                return client.post("/api/search", json={
                    "query": "copper migration survey", "mode": "keyword", "limit": 5,
                }).status_code

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(list(pool.map(concurrent_search, range(4))), [200] * 4)

            self.assertNotEqual(self.index, self.auth_db)
            self.assertTrue((self.index / "index.sqlite").is_file())
            self.assertTrue(self.auth_db.is_file())

        # TestClient shutdown sends SearchService's original quit request. A new app relaunches it on demand.
        restarted = create_app(self.settings, str(self.auth_db), engine_settings=self.engine_settings)
        with TestClient(restarted, base_url="https://testserver") as client:
            client.cookies.set(SESSION_COOKIE, session_cookie)
            status = client.get("/api/engine/status")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()["search_service"], "running")


if __name__ == "__main__":
    unittest.main()
