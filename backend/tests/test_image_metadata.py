from __future__ import annotations

import json
import hashlib
import io
import shutil
import sqlite3
import stat
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.routes.archive import router
from app.auth.authorization import AuthenticatedSession, current_session
from app.auth.database import connect
from app.auth.sessions import SESSION_COOKIE, create_session
from app.core.config import Settings
from app.core.engine_config import EngineSettings
from app.engine.supervisor import DigUpAdapter, MediaNotFound, MediaReference
from app.main import create_app
from app.services.image_metadata import MetadataExtractionFailed, _extract, _normalize, image_metadata


def _png(path: Path) -> None:
    def chunk(name: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + name + payload
                + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF))

    pixels = zlib.compress(b"\x00\x20\x40\x60")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


@unittest.skipUnless(shutil.which("exiftool"), "ExifTool is required for image metadata tests")
class ImageMetadataTests(unittest.TestCase):
    def test_exif_values_are_normalized_and_unrelated_tags_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            image = Path(directory) / "synthetic.png"
            _png(image)
            subprocess.run([
                shutil.which("exiftool") or "exiftool", "-overwrite_original",
                "-Make=Test Camera", "-Model=Test Body", "-LensModel=Test Lens",
                "-FNumber=2.8", "-ExposureTime=0.002", "-ISO=400", "-FocalLength=50",
                "-DateTimeOriginal=2026:11:23 10:20:30",
                "-Copyright=Test Copyright", "-GPSLatitude=12.5", "-GPSLatitudeRef=N",
                "-GPSLongitude=77.25", "-GPSLongitudeRef=E",
                "-XMP-dc:Creator=Synthetic Creator", str(image),
            ], check=True, capture_output=True, text=True)

            result = image_metadata(image)
            self.assertEqual(result["camera"], "Test Camera Test Body")
            self.assertEqual(result["lens"], "Test Lens")
            self.assertEqual(result["aperture"], "f/2.8")
            self.assertEqual(result["shutter_speed"], "1/500 sec")
            self.assertEqual(result["iso"], "400")
            self.assertEqual(result["capture_time"], "2026:11:23 10:20:30")
            self.assertEqual(result["location"], "12.5, 77.25")
            self.assertNotIn("Synthetic Creator", str(result))
            self.assertNotIn("Test Copyright", str(result))

    def test_metadata_without_embedded_tags_is_still_described(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            image = Path(directory) / "plain.png"
            _png(image)
            result = image_metadata(image)
            self.assertEqual(result["dimensions"], "1 × 1 px")
            self.assertTrue(all(value is None for key, value in result.items() if key != "dimensions"))

    def test_authenticated_image_metadata_route_is_session_bound_and_pathless(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            workspace = Path(directory)
            root = workspace / "media"
            root.mkdir()
            image = root / "private.png"
            _png(image)
            engine = EngineSettings(
                executable=workspace / "missing-digup", index_dir=workspace / "index",
                model_dir=workspace / "models", roots=(root,),
            )
            adapter = DigUpAdapter(engine)
            app = create_app(
                Settings(None, None, None, None, 43200, False, "http://testserver"),
                str(workspace / "auth.sqlite"), engine_settings=engine, digup=adapter,
            )
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/media/missing/image-metadata").status_code, 401)
                db = connect(workspace / "auth.sqlite")
                db.execute(
                    "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                    "VALUES('reader','tenant','reader','reader@iihs.ac.in','Reader','EMPLOYEE','ACTIVE','now','now')"
                )
                cookie = create_session(db, "reader", app.state.settings)
                db.commit()
                db.close()
                session_id = cookie.split(".", 1)[0]
                hit = adapter._register_hit({"path": str(image), "kind": "image", "info": {}}, session_id)
                self.assertIsNotNone(hit)
                client.cookies.set(SESSION_COOKIE, cookie)
                response = client.get(f"/api/media/{hit['id']}/image-metadata")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn(str(root), response.text)

                db = connect(workspace / "auth.sqlite")
                db.execute(
                    "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                    "VALUES('other','tenant','other','other@iihs.ac.in','Other','EMPLOYEE','ACTIVE','now','now')"
                )
                other_cookie = create_session(db, "other", app.state.settings)
                db.commit()
                db.close()
                client.cookies.set(SESSION_COOKIE, other_cookie)
                self.assertEqual(client.get(f"/api/media/{hit['id']}/image-metadata").status_code, 404)


class MetadataNormalizationTests(unittest.TestCase):
    def test_image_fields_are_allowlisted_and_preserve_capture_offset_and_precision(self) -> None:
        result = _normalize({
            "IFD0:Make": "Synthetic", "IFD0:Model": "Camera",
            "ExifIFD:LensModel": "Synthetic lens", "ExifIFD:FNumber": "2.8",
            "ExifIFD:ISO": "400", "ExifIFD:ExposureTime": "0.004",
            "ExifIFD:WhiteBalance": "0", "ExifIFD:ExposureCompensation": "0.7",
            "ExifIFD:DateTimeOriginal": "2026:11:23 10:20:30",
            "ExifIFD:SubSecTimeOriginal": "0012", "ExifIFD:OffsetTimeOriginal": "+05:30",
            "GPS:GPSLatitude": "12.123456789", "GPS:GPSLatitudeRef": "S",
            "GPS:GPSLongitude": "77.987654321", "GPS:GPSLongitudeRef": "E",
            "ExifIFD:SerialNumber": "secret", "IFD0:Copyright": "unrelated",
        }, "image")
        self.assertEqual(result, {
            "camera": "Synthetic Camera", "lens": "Synthetic lens", "aperture": "f/2.8",
            "iso": "400", "shutter_speed": "1/250 sec", "white_balance": "Auto",
            "exposure_compensation": "+0.7 EV", "location": "-12.123456789, 77.987654321",
            "capture_time": "2026:11:23 10:20:30.0012+05:30", "dimensions": None,
        })

    def test_missing_values_do_not_use_filesystem_time_or_guess_gps(self) -> None:
        result = _normalize({
            "System:FileModifyDate": "2026:11:23 10:20:30+05:30",
            "GPS:GPSLatitude": "12.5", "GPS:GPSLongitude": "77.25",
            "ExifIFD:WhiteBalance": "7",
        }, "image")
        self.assertTrue(all(value is None for value in result.values()))

    def test_video_container_timestamp_and_coordinates(self) -> None:
        result = _normalize({
            "Keys:Make": "Synthetic", "Keys:Model": "Video",
            "UserData:ContentCreateDate": "2026:11:23 10:20:30.012-04:00",
            "Keys:GPSCoordinates": "+12.123456789-077.987654321+015.000/",
        }, "video")
        self.assertEqual(result["camera"], "Synthetic Video")
        self.assertEqual(result["capture_time"], "2026:11:23 10:20:30.012-04:00")
        self.assertEqual(result["location"], "+12.123456789, -077.987654321")
        self.assertIsNone(result["aperture"])
        self.assertIsNone(_normalize({"QuickTime:CreateDate": "2026:11:23 10:20:30"}, "video")["capture_time"])
        self.assertIsNone(_normalize({"Keys:CreationDate": "2026:11:23 10:20:30"}, "video")["capture_time"])
        self.assertEqual(_normalize({"UserData:ContentCreateDate": "2026:11:23 10:20:30"}, "video")["capture_time"],
                         "2026:11:23 10:20:30")

    def test_dimensions_white_balance_and_malformed_values(self) -> None:
        image = _normalize({"File:ImageWidth": "640", "File:ImageHeight": "480",
                            "ExifIFD:WhiteBalance": "Daylight", "XMP-exif:ExposureTime": "1/250",
                            "ExifIFD:DateTimeOriginal": "2026:19:40 10:20:30"}, "image")
        self.assertEqual(image["dimensions"], "640 × 480 px")
        self.assertEqual(image["white_balance"], "Daylight")
        self.assertEqual(image["shutter_speed"], "1/250 sec")
        self.assertIsNone(image["capture_time"])
        self.assertEqual(_normalize({"ExifIFD:LensMake": "Test", "ExifIFD:LensModel": "Test 50mm"}, "image")["lens"], "Test 50mm")
        self.assertIsNone(_normalize({"ExifIFD:WhiteBalance": "unrecognized value"}, "image")["white_balance"])
        self.assertEqual(_normalize({"XMP-exif:GPSLatitude": "-12.123456", "XMP-exif:GPSLongitude": "77.25"}, "image")["location"],
                         "-12.123456, 77.25")
        self.assertIsNone(_normalize({"PNG:ImageWidth": "-1", "PNG:ImageHeight": "480"}, "image")["dimensions"])
        self.assertIsNone(_normalize({"ExifIFD:DateTimeOriginal": "2026:11:23 10:20:30",
                                      "ExifIFD:OffsetTimeOriginal": "+25:00"}, "image")["capture_time"])

    def test_extraction_failure_does_not_expose_tool_output(self) -> None:
        failure = SimpleNamespace(returncode=1, stdout="bad json from /private/image.jpg", stderr="secret")
        with patch("app.services.image_metadata._metadata_tool", return_value="/synthetic/exiftool"), \
                patch("app.services.image_metadata.subprocess.run", return_value=failure):
            with self.assertRaises(MetadataExtractionFailed) as error:
                _extract(Path("/private/image.jpg"), "image")
        self.assertNotIn("/private", str(error.exception))

    @unittest.skipUnless(shutil.which("exiftool"), "ExifTool is required")
    def test_exiftool_reads_synthetic_exif_from_memory(self) -> None:
        extra = bytearray()
        def append(value: bytes) -> int:
            offset = 158 + len(extra)
            extra.extend(value)
            return offset
        def entry(tag: int, kind: int, count: int, value: int) -> bytes:
            return struct.pack("<HHII", tag, kind, count, value)
        make = append(b"Synthetic\0")
        date = append(b"2026:11:23 10:20:30\0")
        fraction = append(b"0012\0")
        offset = append(b"+05:30\0")
        exposure = append(struct.pack("<II", 1, 250))
        lat = append(struct.pack("<IIIIII", 12, 1, 30, 1, 0, 1))
        lon = append(struct.pack("<IIIIII", 77, 1, 15, 1, 0, 1))
        ifd0 = struct.pack("<H", 3) + entry(0x010F, 2, 10, make) + entry(0x8769, 4, 1, 50) + entry(0x8825, 4, 1, 104) + bytes(4)
        exif = (struct.pack("<H", 4) + entry(0x9003, 2, 20, date) + entry(0x9291, 2, 5, fraction)
                + entry(0x9011, 2, 7, offset) + entry(0x829A, 5, 1, exposure) + bytes(4))
        gps = (struct.pack("<H", 4) + entry(1, 2, 2, ord("S")) + entry(2, 5, 3, lat)
               + entry(3, 2, 2, ord("E")) + entry(4, 5, 3, lon) + bytes(4))
        tiff = b"II*\x00\x08\x00\x00\x00" + ifd0 + exif + gps + extra
        output = subprocess.run(
            [shutil.which("exiftool") or "exiftool", "-j", "-api", "structformat=jsonq",
             "-G1", "-s", "-a", "-n", "-"],
            input=tiff, capture_output=True, check=True,
        )
        result = _normalize(json.loads(output.stdout)[0], "image")
        self.assertEqual(result["camera"], "Synthetic")
        self.assertEqual(result["capture_time"], "2026:11:23 10:20:30.0012+05:30")
        self.assertEqual(result["shutter_speed"], "1/250 sec")
        self.assertEqual(result["location"], "-12.5, 77.25")

    @unittest.skipUnless(shutil.which("exiftool") and shutil.which("ffmpeg"), "ExifTool and FFmpeg are required")
    def test_exiftool_reads_synthetic_quicktime_from_memory(self) -> None:
        video = subprocess.run([
            shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=16x16:d=0.1", "-c:v", "mpeg4",
            "-movflags", "frag_keyframe+empty_moov+use_metadata_tags",
            "-metadata", "com.apple.quicktime.make=Synthetic",
            "-metadata", "com.apple.quicktime.model=Video",
            "-metadata", "com.apple.quicktime.creationdate=2026-11-23T10:20:30.012-04:00",
            "-metadata", "com.apple.quicktime.location.ISO6709=+12.123456789-077.987654321/",
            "-f", "mov", "pipe:1",
        ], capture_output=True, check=True).stdout
        output = subprocess.run([
            shutil.which("exiftool") or "exiftool", "-j", "-api", "structformat=jsonq",
            "-G1", "-s", "-a", "-n", "-",
        ], input=video, capture_output=True, check=True)
        result = _normalize(json.loads(output.stdout)[0], "video")
        self.assertEqual(result["camera"], "Synthetic Video")
        self.assertIsNone(result["capture_time"])
        self.assertEqual(result["location"], "12.123456789, -77.987654321")
        self.assertEqual(result["dimensions"], "16 × 16 px")


class MetadataRouteTests(unittest.TestCase):
    def test_video_gps_requires_the_issuing_session(self) -> None:
        app = FastAPI()
        app.include_router(router)
        class Adapter:
            def media(self, handle: str, *, session_id: str) -> MediaReference:
                if handle != "synthetic" or session_id != "owner":
                    raise MediaNotFound("Not found")
                return MediaReference(Path("/synthetic/video.mov"), Path("/synthetic"),
                                      {"kind": "video"}, session_id, 0)
        app.state.digup = Adapter()
        def session(request: Request) -> AuthenticatedSession:
            identifier = request.headers.get("X-Test-Session")
            if not identifier:
                raise HTTPException(status_code=401, detail="Authentication required")
            return AuthenticatedSession(identifier, identifier, "EMPLOYEE", "", "", "", False)
        app.dependency_overrides[current_session] = session
        data = _normalize({"Keys:GPSCoordinates": "+12.5+077.25/"}, "video")
        with patch("app.api.routes.archive.image_metadata", return_value=data) as extract, TestClient(app) as client:
            anonymous = client.get("/api/media/synthetic/image-metadata")
            other = client.get("/api/media/synthetic/image-metadata", headers={"X-Test-Session": "other"})
            self.assertEqual(anonymous.status_code, 401)
            self.assertEqual(other.status_code, 404)
            self.assertNotIn("12.5", anonymous.text + other.text)
            extract.assert_not_called()
            owner = client.get("/api/media/synthetic/image-metadata", headers={"X-Test-Session": "owner"})
            self.assertEqual(owner.status_code, 200)
            self.assertEqual(owner.json()["location"], "+12.5, +077.25")
            self.assertEqual(owner.headers["cache-control"], "private, no-store")

    def test_real_session_checks_gate_image_gps(self) -> None:
        uri = "file:stage4h_metadata_test?mode=memory&cache=shared"
        def connection() -> sqlite3.Connection:
            db = sqlite3.connect(uri, uri=True, isolation_level=None)
            db.row_factory = sqlite3.Row
            return db
        anchor = connection()
        try:
            anchor.executescript("""
                CREATE TABLE users(id TEXT PRIMARY KEY, email TEXT, display_name TEXT, role TEXT, status TEXT);
                CREATE TABLE sessions(id TEXT PRIMARY KEY, user_id TEXT, session_secret_hash TEXT,
                    created_at TEXT, last_seen_at TEXT, expires_at TEXT, revoked_at TEXT);
                CREATE TABLE local_credentials(user_id TEXT, must_change_password INTEGER);
                INSERT INTO users VALUES('owner', 'owner@example.test', 'Owner', 'EMPLOYEE', 'ACTIVE');
                INSERT INTO users VALUES('other', 'other@example.test', 'Other', 'EMPLOYEE', 'ACTIVE');
            """)
            settings = Settings(None, None, None, None, 43200, True, "http://testserver")
            owner_cookie = create_session(anchor, "owner", settings)
            other_cookie = create_session(anchor, "other", settings)
            owner_session_id = owner_cookie.split(".", 1)[0]
            class Adapter:
                def media(self, handle: str, *, session_id: str) -> MediaReference:
                    if handle != "synthetic" or session_id != owner_session_id:
                        raise MediaNotFound("Not found")
                    return MediaReference(Path("/synthetic/photo.jpg"), Path("/synthetic"),
                                          {"kind": "image"}, session_id, 0)
            app = FastAPI()
            app.include_router(router)
            app.state.digup = Adapter()
            app.state.db_path = None
            data = _normalize({"GPS:GPSLatitude": "12.5", "GPS:GPSLatitudeRef": "N",
                               "GPS:GPSLongitude": "77.25", "GPS:GPSLongitudeRef": "E"}, "image")
            with patch("app.auth.authorization.connect", side_effect=lambda _: connection()), \
                    patch("app.api.routes.archive.image_metadata", return_value=data) as extract, TestClient(app) as client:
                self.assertEqual(client.get("/api/media/synthetic/image-metadata").status_code, 401)
                client.cookies.set(SESSION_COOKIE, other_cookie)
                self.assertEqual(client.get("/api/media/synthetic/image-metadata").status_code, 404)
                extract.assert_not_called()
                client.cookies.set(SESSION_COOKIE, owner_cookie)
                self.assertEqual(client.get("/api/media/synthetic/image-metadata").json()["location"], "12.5, 77.25")
                anchor.execute("UPDATE users SET status='DEACTIVATED' WHERE id='owner'")
                self.assertEqual(client.get("/api/media/synthetic/image-metadata").status_code, 401)
        finally:
            anchor.close()


class FileDetailsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.info = SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4,
                                    st_ctime_ns=5, st_mode=stat.S_IFREG | 0o600)
        self.path = Mock()
        self.path.name = "photo.jpg"
        self.path.relative_to.return_value = Path("folder/photo.jpg")
        self.path.stat.return_value = self.info
        path = self.path
        class Adapter:
            def media(self, handle: str, *, session_id: str):
                if handle != "synthetic" or session_id != "owner":
                    raise MediaNotFound("Not found")
                return SimpleNamespace(path=path, root=Path("/private/root"), hit={"kind": "image"}, code=False)
        app = FastAPI()
        app.include_router(router)
        app.state.digup = Adapter()
        def session(request: Request) -> AuthenticatedSession:
            identifier = request.headers.get("X-Test-Session")
            if not identifier:
                raise HTTPException(status_code=401, detail="Authentication required")
            return AuthenticatedSession(identifier, identifier, "EMPLOYEE", "", "", "", False)
        app.dependency_overrides[current_session] = session
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_details_are_relative_and_session_bound(self) -> None:
        self.assertEqual(self.client.get("/api/media/synthetic").status_code, 401)
        self.assertEqual(self.client.get("/api/media/synthetic", headers={"X-Test-Session": "other"}).status_code, 404)
        response = self.client.get("/api/media/synthetic", headers={"X-Test-Session": "owner"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_relative_path"], "folder/photo.jpg")
        self.assertEqual(response.json()["current_size"], 3)
        self.assertNotIn("/private/root", response.text)
        self.path.relative_to.side_effect = ValueError("outside /private/root")
        forbidden = self.client.get("/api/media/synthetic", headers={"X-Test-Session": "owner"})
        self.assertEqual(forbidden.status_code, 403)
        self.assertNotIn("/private/root", forbidden.text)

    def test_checksum_is_streamed_authorized_and_detects_changes(self) -> None:
        class Stream(io.BytesIO):
            def fileno(self) -> int:
                return 42
        with patch("app.api.routes.archive.os.open", return_value=42) as open_file, \
                patch("app.api.routes.archive.os.fdopen", side_effect=lambda *_: Stream(b"abc")), \
                patch("app.api.routes.archive.os.fstat", return_value=self.info):
            self.assertEqual(self.client.get("/api/media/synthetic/checksum").status_code, 401)
            self.assertEqual(self.client.get("/api/media/synthetic/checksum", headers={"X-Test-Session": "other"}).status_code, 404)
            open_file.assert_not_called()
            response = self.client.get("/api/media/synthetic/checksum", headers={"X-Test-Session": "owner"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sha256"], hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(response.headers["cache-control"], "private, no-store")

        changed = SimpleNamespace(**{**vars(self.info), "st_size": 4})
        with patch("app.api.routes.archive.os.open", return_value=42), \
                patch("app.api.routes.archive.os.fdopen", side_effect=lambda *_: Stream(b"abc")), \
                patch("app.api.routes.archive.os.fstat", side_effect=[self.info, changed]):
            response = self.client.get("/api/media/synthetic/checksum", headers={"X-Test-Session": "owner"})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("/private/root", response.text)

    def test_checksum_read_errors_do_not_disclose_path(self) -> None:
        self.path.stat.side_effect = OSError("private path /secret/photo.jpg")
        response = self.client.get("/api/media/synthetic/checksum", headers={"X-Test-Session": "owner"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("/secret", response.text)
        self.path.stat.side_effect = FileNotFoundError("/secret/photo.jpg")
        missing = self.client.get("/api/media/synthetic/checksum", headers={"X-Test-Session": "owner"})
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn("/secret", missing.text)


if __name__ == "__main__":
    unittest.main()
