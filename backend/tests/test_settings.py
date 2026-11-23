from __future__ import annotations

import asyncio
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.engine_config import EngineSettings
from app.auth.database import connect
from app.auth.sessions import SESSION_COOKIE, create_session
from app.engine.supervisor import DigUpAdapter, IndexJob
from app.main import create_app
from app.settings.browser import DirectoryBrowser, DirectoryUnavailable
from app.settings.schemas import ExtensionUpdate
from app.settings.service import SettingsService


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.workspace = Path(self.tmp.name)
        self.volume = self.workspace / "volume"
        (self.volume / "archive" / "private" / "generated").mkdir(parents=True)
        (self.volume / "code" / "build").mkdir(parents=True)
        self.outside = self.workspace / "outside"
        self.outside.mkdir()
        self.browser = DirectoryBrowser(test_volumes=((self.volume, "Test drive"),))
        self.path = self.workspace / "settings.json"
        self.engine = EngineSettings(
            executable=self.workspace / "digup", index_dir=self.workspace / "index",
            model_dir=self.workspace / "models", roots=(),
        )
        self.service = SettingsService(self.engine, path=self.path, browser=self.browser)

    def _login(self, client: TestClient, db_path: Path, settings: Settings,
               role: str = "ARCHIVE_OPERATOR") -> str:
        db = connect(db_path)
        user_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,'ACTIVE','now','now')",
            (user_id, "tenant", user_id, f"{user_id}@iihs.ac.in", "Test user", role),
        )
        cookie = create_session(db, user_id, settings)
        db.commit()
        db.close()
        client.cookies.set(SESSION_COOKIE, cookie)
        return client.get("/auth/session").headers["x-csrf-token"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def browse_ref(self, path: Path) -> str:
        volume = self.browser.volumes()[0]
        result = self.browser.browse(volume_ref=volume["ref"])
        current = result["current"]["ref"]
        relative = path.relative_to(self.volume)
        for part in relative.parts:
            result = self.browser.browse(directory_ref=current)
            current = next(item["ref"] for item in result["entries"] if item["name"] == part)
        return current

    def test_defaults_and_persistence_across_service_restart(self) -> None:
        self.assertEqual(self.service.general()["indexing_behavior"], "manual")
        self.assertEqual(self.service.folders()["roots"], [])
        ref = self.browse_ref(self.volume / "archive")
        self.service.add_root(ref, section="folders")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        restarted = SettingsService(self.engine, path=self.path,
                                    browser=DirectoryBrowser(test_volumes=((self.volume, "Test drive"),)))
        self.assertEqual(restarted.engine_settings().roots, (self.volume / "archive",))
        self.assertEqual(restarted.folders()["roots"][0]["name"], "archive")

    def test_safe_browser_lists_only_directories_and_hides_files_and_symlinks(self) -> None:
        (self.volume / "archive" / "visible.txt").write_text("fixture")
        (self.volume / "archive" / "escape").symlink_to(self.outside, target_is_directory=True)
        ref = self.browse_ref(self.volume / "archive")
        listing = self.browser.browse(directory_ref=ref)
        self.assertEqual([item["name"] for item in listing["entries"]], ["private"])
        with self.assertRaises(DirectoryUnavailable):
            self.browser.issue_root_directory(self.outside, self.volume, "Test drive")

    def test_directory_traversal_and_disconnected_volume_are_rejected(self) -> None:
        volume = self.browser.volumes()[0]
        with self.assertRaises(DirectoryUnavailable):
            self.browser.browse(volume_ref="../" + volume["ref"])
        self.volume.rename(self.workspace / "disconnected")
        rows = self.browser.volumes()
        self.assertFalse(rows[0]["available"])
        with self.assertRaises(DirectoryUnavailable):
            self.browser.browse(volume_ref=rows[0]["ref"])

    def test_volume_and_settings_responses_do_not_expose_absolute_paths(self) -> None:
        ref = self.browse_ref(self.volume / "archive")
        self.service.add_root(ref, section="folders")
        public = str(self.service.all()) + str(self.service.volumes())
        self.assertNotIn(str(self.workspace), public)

    def test_exclusions_are_limited_to_configured_roots_and_persist(self) -> None:
        root_ref = self.browse_ref(self.volume / "archive")
        root = self.service.add_root(root_ref, section="folders")["roots"][0]
        exclusion_ref = self.browse_ref(self.volume / "archive" / "private")
        self.service.add_exclusion(exclusion_ref, section="folders")
        self.assertEqual(self.service.engine_settings().excluded_folders,
                         (self.volume / "archive" / "private",))
        with self.assertRaises(ValueError):
            before = self.path.read_bytes()
            self.service.add_exclusion(self.browse_ref(self.volume / "code"), section="folders")
        self.assertEqual(self.path.read_bytes(), before)
        self.service.remove_root(root["id"], section="folders")
        self.assertEqual(self.service.folders()["excluded_folders"], [])

    def test_removing_parent_root_preserves_exclusion_still_valid_under_nested_root(self) -> None:
        outer_ref = self.browse_ref(self.volume / "archive")
        outer = self.service.add_root(outer_ref, section="folders")["roots"][0]
        nested_ref = self.browse_ref(self.volume / "archive" / "private")
        self.service.add_root(nested_ref, section="folders")
        excluded_ref = self.browse_ref(self.volume / "archive" / "private" / "generated")
        self.service.add_exclusion(excluded_ref, section="folders")
        self.service.remove_root(outer["id"], section="folders")
        self.assertEqual(self.service.engine_settings().excluded_folders,
                         (self.volume / "archive" / "private" / "generated",))

    def test_code_roots_and_exclusions_map_separately(self) -> None:
        root = self.browse_ref(self.volume / "code")
        self.service.add_root(root, section="code")
        exclusion = self.browse_ref(self.volume / "code" / "build")
        self.service.add_exclusion(exclusion, section="code")
        settings = self.service.engine_settings()
        self.assertEqual(settings.roots, ())
        self.assertEqual(settings.code_roots, (self.volume / "code",))
        self.assertEqual(settings.code_excluded_folders, (self.volume / "code" / "build",))
        self.assertTrue(self.service.code()["search_available"])

    def test_extension_update_normalizes_and_rejects_invalid_values(self) -> None:
        self.assertEqual(ExtensionUpdate(extensions=[".TMP", " log ", "*.tmp"]).extensions, ["log", "tmp"])
        with self.assertRaises(ValidationError):
            ExtensionUpdate(extensions=["../private"])
        self.service.set_extensions(ExtensionUpdate(extensions=[".TMP", ".log"]).extensions)
        self.assertEqual(self.service.engine_settings().excluded_extensions, ("log", "tmp"))

    def test_bad_existing_configuration_is_left_unchanged(self) -> None:
        self.path.write_text('{"version": 99}', encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(Exception):
            SettingsService(self.engine, path=self.path, browser=self.browser)
        self.assertEqual(self.path.read_bytes(), before)

    def test_index_service_receives_configured_roots_and_exclusions(self) -> None:
        root = self.volume / "archive"
        exclusion = root / "private"
        code_root = self.volume / "code"
        settings = EngineSettings(
            executable=self.workspace / "digup", index_dir=self.workspace / "index",
            model_dir=self.workspace / "models", roots=(root,), excluded_folders=(exclusion,),
            excluded_extensions=("tmp", "log"), code_roots=(code_root,),
            code_excluded_folders=(code_root / "build",),
        )
        job = IndexJob(settings)
        captured: list[list[str]] = []

        class Input:
            def write(self, _: bytes) -> None:
                pass

            async def drain(self) -> None:
                pass

        class EmptyStream:
            async def __aiter__(self):
                if False:
                    yield b""

        class Process:
            stdin = Input()
            stdout = EmptyStream()
            stderr = None

            async def wait(self) -> int:
                return 0

        async def spawn(*args, **kwargs):
            captured.append(list(args))
            return Process()

        async def verify() -> None:
            settings.executable.touch()
            settings.executable.chmod(0o755)
            job.settings = settings
            with patch("asyncio.create_subprocess_exec", new=spawn):
                await job.start()
                await job._task
                code_only = EngineSettings(
                    executable=settings.executable, index_dir=settings.index_dir, model_dir=settings.model_dir,
                    roots=(), code_roots=(code_root,), code_excluded_folders=(code_root / "build",),
                )
                code_job = IndexJob(code_only)
                await code_job.start()
                await code_job._task

        asyncio.run(verify())
        self.assertIn("--prune", captured[0])
        self.assertEqual(captured[0].count("--exclude"), 1)
        self.assertEqual(captured[0].count("--exclude-ext"), 2)
        self.assertEqual(captured[0].count("--code-root"), 1)
        self.assertEqual(captured[0].count("--code-exclude"), 1)
        self.assertIn(str(root), captured[0])
        self.assertNotIn("--prune", captured[1])

    def test_indexing_refuses_disconnected_roots_before_starting_process(self) -> None:
        async def verify() -> None:
            settings = EngineSettings(
                executable=self.workspace / "digup", index_dir=self.workspace / "index",
                model_dir=self.workspace / "models", roots=(self.workspace / "missing",),
            )
            settings.executable.touch()
            settings.executable.chmod(0o755)
            job = IndexJob(settings)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                await job.start()

        asyncio.run(verify())

    def test_settings_api_and_storage_require_an_authorized_session(self) -> None:
        settings = Settings(None, None, None, None, 43200, True, "https://testserver")
        db_path = self.workspace / "auth.sqlite"
        app = create_app(settings, str(db_path), engine_settings=self.engine,
                         settings_path=str(self.path),
                         settings_service=self.service)
        with TestClient(app, base_url="https://testserver") as client:
            self.assertEqual(client.get("/api/settings").status_code, 401)
            self._login(client, db_path, settings)
            self.assertEqual(client.get("/api/settings").status_code, 200)
            response = client.get("/api/settings/storage")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(str(self.workspace), response.text)
        with TestClient(app, base_url="https://testserver", client=("192.0.2.1", 1234)) as remote_client:
            self._login(remote_client, db_path, settings)
            self.assertEqual(remote_client.get("/api/settings").status_code, 200)

    def test_folder_api_accepts_only_opaque_references_and_applies_configuration(self) -> None:
        settings = Settings(None, None, None, None, 43200, True, "https://testserver")
        db_path = self.workspace / "auth.sqlite"
        app = create_app(settings, str(db_path), engine_settings=self.engine,
                         settings_path=str(self.path), settings_service=self.service)
        with TestClient(app, base_url="https://testserver") as client:
            csrf = self._login(client, db_path, settings)
            volume = client.get("/api/settings/volumes").json()["volumes"][0]
            listing = client.get("/api/settings/browse", params={"volume_ref": volume["ref"]}).json()
            folder = next(item for item in listing["entries"] if item["name"] == "archive")
            no_csrf = client.post("/api/settings/folders/roots", json={"directory_ref": folder["ref"]})
            self.assertEqual(no_csrf.status_code, 403)
            headers = {"origin": "https://testserver", "x-csrf-token": csrf}
            response = client.post("/api/settings/folders/roots", json={"directory_ref": folder["ref"]}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(app.state.digup.settings.roots, (self.volume / "archive",))
            rejected = client.post("/api/settings/folders/roots", json={"path": "/private"}, headers=headers)
            self.assertEqual(rejected.status_code, 422)

    def test_settings_apply_to_running_search_service(self) -> None:
        adapter = DigUpAdapter(self.engine)
        adapter.search_process.process = type("Process", (), {"returncode": None})()
        adapter.search_process.request = AsyncMock(return_value={"ok": True})
        updated = EngineSettings(
            executable=self.engine.executable, index_dir=self.engine.index_dir, model_dir=self.engine.model_dir,
            roots=(self.volume / "archive",), excluded_folders=(self.volume / "archive" / "private",),
            excluded_extensions=("tmp",), code_roots=(self.volume / "code",),
            code_excluded_folders=(self.volume / "code" / "build",),
        )
        asyncio.run(adapter.configure(updated))
        kwargs = adapter.search_process.request.await_args.kwargs
        self.assertEqual(kwargs["roots"], [str(self.volume / "archive")])
        self.assertEqual(kwargs["skipped"], [str(self.volume / "archive" / "private")])
        self.assertEqual(kwargs["types"], ["tmp"])
        self.assertEqual(kwargs["code_roots"], [str(self.volume / "code")])
        self.assertEqual(kwargs["code_skipped"], [str(self.volume / "code" / "build")])


if __name__ == "__main__":
    unittest.main()
