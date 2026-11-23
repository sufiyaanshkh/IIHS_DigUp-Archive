from __future__ import annotations

import concurrent.futures
import struct
import subprocess
import tempfile
import time
import unittest
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.engine_config import EngineSettings, MEDIA_PROJECTOR, TEXT_MODEL
from app.auth.database import connect
from app.auth.sessions import SESSION_COOKIE, create_session
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = PROJECT_ROOT / "backend" / "engine" / "DigUp"
CLI = ENGINE_ROOT / ".build" / "release" / "digup"
MODELS = ENGINE_ROOT / "Vendor" / "models"


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


@unittest.skipUnless(
    CLI.is_file() and all((MODELS / name).is_file() for name in (TEXT_MODEL, MEDIA_PROJECTOR)),
    "the pinned DigUp CLI and approved model files are required",
)
class ArchiveApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.workspace = Path(self.tmp.name)
        self.root = self.workspace / "media"
        self.root.mkdir()
        self.index = self.workspace / "index"
        self.auth_db = self.workspace / "auth.sqlite"
        (self.root / "rainfall-notes.txt").write_text(
            "The saffron observatory records monsoon rainfall across the western district.\n", encoding="utf-8"
        )
        (self.root / "coastal-survey.txt").write_text(
            "A copper migration survey follows coastal households from 1984.\n", encoding="utf-8"
        )
        (self.root / "harbor-log.txt").write_text(
            "The lighthouse keeper recorded a severe storm warning near the northern harbor.\n", encoding="utf-8"
        )
        _png(self.root / "color-study.png")
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
            executable=CLI.resolve(), index_dir=self.index.resolve(), model_dir=MODELS.resolve(),
            roots=(self.root.resolve(),), request_timeout_seconds=60,
        )
        self.settings = Settings(None, None, None, None, 43200, True, "https://testserver")
        self.app = create_app(self.settings, str(self.auth_db), engine_settings=self.engine_settings)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _index(self, client: TestClient, csrf: str) -> dict:
        response = client.post("/api/indexing/sync", headers={
            "origin": "https://testserver", "x-csrf-token": csrf,
        })
        self.assertEqual(response.status_code, 202, response.text)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = client.get("/api/indexing/status").json()
            if status["state"] in ("completed", "failed", "stopped"):
                return status
            time.sleep(0.1)
        self.fail("IndexService did not finish before the test timeout")

    def test_index_search_preview_metadata_download_concurrency_and_restart(self) -> None:
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
            self.assertTrue(health["models_available"])
            self.assertEqual(client.get("/api/engine/status").status_code, 200)
            status = self._index(client, csrf)
            self.assertEqual(status["state"], "completed", status)
            self.assertEqual(status.get("search_reload"), "complete")
            self.assertTrue(status["summary_available"])
            self.assertGreaterEqual(status["roots"][0]["files"], 5 if self.ffmpeg else 4)
            self.assertTrue(any(event.get("event") == "file" for event in status["events"]))
            self.assertFalse(any("/" in str(event.get("path", "")) for event in status["events"]))

            keyword = client.post("/api/search", json={
                "query": "monsoon rainfall", "mode": "keyword", "limit": 10,
            })
            self.assertEqual(keyword.status_code, 200, keyword.text)
            self.assertFalse(keyword.json()["meaning"])
            self.assertEqual(keyword.json()["hits"][0]["name"], "rainfall-notes.txt")

            hybrid = client.post("/api/search", json={
                "query": "rainfall records from the western district in the wet season",
                "mode": "hybrid", "limit": 10,
            })
            self.assertEqual(hybrid.status_code, 200, hybrid.text)
            self.assertTrue(hybrid.json()["meaning"])
            self.assertEqual(hybrid.json()["hits"][0]["name"], "rainfall-notes.txt")

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
            self.assertEqual(client.post("/api/search", json={"query": "   "}).status_code, 422)

            if self.ffmpeg:
                video_hits = client.post("/api/search", json={
                    "query": "sequence.mov", "mode": "keyword", "kinds": ["video"],
                }).json()["hits"]
                video_hit = next(hit for hit in video_hits if hit["name"] == "sequence.mov")
                frame = client.get(f"/api/media/{video_hit['id']}/frame?at=3.5")
                self.assertEqual(frame.status_code, 200, frame.text)
                self.assertEqual(frame.headers["content-type"], "image/jpeg")

            def concurrent_search(_: int) -> int:
                return client.post("/api/search", json={
                    "query": "copper migration survey", "mode": "hybrid", "limit": 5,
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
