from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import unittest
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.authorization import AuthenticatedSession, current_session, require_csrf
from app.auth.sessions import SESSION_COOKIE, create_session, csrf_token
from app.core.config import Settings
from app.core.engine_config import EngineSettings
from app.engine.supervisor import DigUpAdapter
from app.settings.browser import DirectoryUnavailable
from app.settings.native_picker import NativePickerUnavailable, choose_folders
from app.settings.routes import router
from app.settings.service import PathEntry, SettingsDocument, SettingsService


class NativePickerTests(unittest.TestCase):
    def test_macos_multi_select_and_cancel(self) -> None:
        result = SimpleNamespace(returncode=0, stdout=json.dumps(["/synthetic/one", "/Volumes/Synthetic/folder\nα"]))
        with patch.dict(os.environ, {"IIHS_NATIVE_FOLDER_PICKER": "1"}), \
                patch("app.settings.native_picker.sys.platform", "darwin"), \
                patch("app.settings.native_picker.shutil.which", return_value="/usr/bin/osascript"), \
                patch("app.settings.native_picker.subprocess.run", return_value=result) as run:
            self.assertEqual(choose_folders("http://127.0.0.1:3017"), ["/synthetic/one", "/Volumes/Synthetic/folder\nα"])
            self.assertEqual(run.call_args.args[0][1:3], ["-l", "JavaScript"])
            result.stdout = "[]"
            self.assertEqual(choose_folders("http://localhost:3017"), [])

    def test_platform_helpers_are_selected_without_a_shell(self) -> None:
        for platform, executable, suffix in (("win32", "powershell.exe", "native_picker_windows.ps1"),
                                             ("linux", None, "native_picker_linux.py")):
            result = SimpleNamespace(returncode=0, stdout="[]")
            with patch.dict(os.environ, {"IIHS_NATIVE_FOLDER_PICKER": "1", "PRIVATE_SECRET": "not forwarded"}), \
                    patch("app.settings.native_picker.sys.platform", platform), \
                    patch("app.settings.native_picker.shutil.which", return_value=executable), \
                    patch("app.settings.native_picker.subprocess.run", return_value=result) as run:
                self.assertEqual(choose_folders("http://127.0.0.1:3017"), [])
                self.assertTrue(run.call_args.args[0][-1].endswith(suffix))
                self.assertNotIn("PRIVATE_SECRET", run.call_args.kwargs["env"])

    def test_picker_is_opt_in_and_local_only(self) -> None:
        with patch.dict(os.environ, {"IIHS_NATIVE_FOLDER_PICKER": "1"}), \
                patch("app.settings.native_picker.subprocess.run") as run:
            for origin in (None, "http://example.test", "http://localhost.example.test", "http://localhost:bad"):
                with self.assertRaises(NativePickerUnavailable):
                    choose_folders(origin)
            run.assert_not_called()
        with patch.dict(os.environ, {"IIHS_NATIVE_FOLDER_PICKER": "0"}):
            with self.assertRaises(NativePickerUnavailable):
                choose_folders("http://127.0.0.1:3017")

    def test_tool_failure_and_invalid_results_are_explicit(self) -> None:
        with patch.dict(os.environ, {"IIHS_NATIVE_FOLDER_PICKER": "1"}), \
                patch("app.settings.native_picker._command", return_value=["synthetic"]):
            for outcome in (
                SimpleNamespace(returncode=1, stdout=""),
                SimpleNamespace(returncode=0, stdout='["valid", null]'),
                subprocess.TimeoutExpired("synthetic", 300),
            ):
                with patch("app.settings.native_picker.subprocess.run", side_effect=[outcome]):
                    with self.assertRaises(NativePickerUnavailable):
                        choose_folders("http://127.0.0.1:3017")


class NativeRootsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(SettingsService)
        self.service._lock = RLock()
        self.old = PathEntry(id="a" * 32, path="/synthetic/old", volume_path="/synthetic/old",
                             volume_label="old", name="old", relative_path=".")
        self.excluded = PathEntry(id="b" * 32, path="/synthetic/old/private", volume_path="/synthetic/old",
                                  volume_label="old", name="private", relative_path="private")
        self.service._document = SettingsDocument(roots=[self.old], excluded_folders=[self.excluded])

    def test_multiple_roots_are_added_atomically_and_duplicates_are_skipped(self) -> None:
        def stat(path: Path):
            inode = {"/synthetic/old": 1, "/synthetic/new": 2, "/synthetic/other": 3}[str(path)]
            return SimpleNamespace(st_dev=1, st_ino=inode)
        with patch.object(SettingsService, "_native_root", side_effect=lambda value: Path(value)), \
                patch.object(Path, "stat", stat), \
                patch.object(SettingsService, "_commit") as commit, \
                patch.object(SettingsService, "folders", return_value={}) as folders:
            self.service.add_native_roots(["/synthetic/new", "/synthetic/new", "/synthetic/other"])
        candidate = commit.call_args.args[0]
        self.assertEqual([item.path for item in candidate.roots], ["/synthetic/old", "/synthetic/new", "/synthetic/other"])
        self.assertEqual(candidate.excluded_folders, [self.excluded])
        commit.assert_called_once()
        folders.assert_called_once()

    def test_disconnected_or_forbidden_selection_never_commits(self) -> None:
        with patch.object(SettingsService, "_native_root", side_effect=[Path("/synthetic/ok"), DirectoryUnavailable("unavailable")]), \
                patch.object(SettingsService, "_commit") as commit:
            with self.assertRaises(DirectoryUnavailable):
                self.service.add_native_roots(["/synthetic/ok", "/synthetic/disconnected"])
            commit.assert_not_called()

    def test_rejects_traversal_and_linked_path(self) -> None:
        with self.assertRaises(DirectoryUnavailable):
            SettingsService._native_root("/synthetic/../outside")
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(DirectoryUnavailable):
                SettingsService._native_root("/synthetic/link")
        with patch.object(Path, "is_symlink", return_value=False), \
                patch.object(Path, "is_junction", return_value=True, create=True):
            with self.assertRaises(DirectoryUnavailable):
                SettingsService._native_root("/synthetic/junction")

    def test_permission_denial_is_reported_without_committing(self) -> None:
        with patch.object(Path, "is_symlink", return_value=False), \
                patch.object(Path, "is_junction", return_value=False, create=True), \
                patch.object(Path, "resolve", return_value=Path("/synthetic/private")), \
                patch.object(Path, "is_dir", return_value=True), \
                patch("app.settings.service.os.scandir", side_effect=PermissionError("private")):
            with self.assertRaises(DirectoryUnavailable) as error:
                SettingsService._native_root("/synthetic/private")
        self.assertNotIn("/synthetic/private", str(error.exception))


class NativePickerRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = AuthenticatedSession("owner", "session", "ARCHIVE_OPERATOR", "", "", "", False)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.state.settings = SimpleNamespace(public_origin="http://127.0.0.1:3017")
        self.app.state.settings_service = SimpleNamespace(folders=Mock(return_value={"roots": []}),
                                                          add_native_roots=Mock(return_value={"roots": ["new"]}))
        self.app.dependency_overrides[current_session] = lambda: self.session
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app, client=("127.0.0.1", 1234))

    def test_cancel_does_not_save_or_configure(self) -> None:
        with patch("app.settings.routes.choose_folders", return_value=[]), \
                patch("app.settings.routes._apply", new_callable=AsyncMock) as apply:
            response = self.client.post("/api/settings/folders/native-roots")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cancelled"])
        self.app.state.settings_service.add_native_roots.assert_not_called()
        apply.assert_not_awaited()

    def test_multiple_selected_folders_are_saved_once_without_indexing(self) -> None:
        with patch("app.settings.routes.choose_folders", return_value=["/synthetic/a", "/synthetic/b"]), \
                patch("app.settings.routes.active_session", return_value=self.session), \
                patch("app.settings.routes._apply", new_callable=AsyncMock) as apply:
            response = self.client.post("/api/settings/folders/native-roots")
        self.assertEqual(response.status_code, 200)
        self.app.state.settings_service.add_native_roots.assert_called_once_with(["/synthetic/a", "/synthetic/b"])
        apply.assert_awaited_once()

    def test_real_configuration_apply_does_not_start_indexing(self) -> None:
        engine = EngineSettings(executable=Path("/synthetic/digup"), index_dir=Path("/synthetic/index"),
                                model_dir=Path("/synthetic/models"), roots=())
        adapter = DigUpAdapter(engine)
        self.app.state.digup = adapter
        self.app.state.settings_service.engine_settings = Mock(return_value=engine)
        with patch("app.settings.routes.choose_folders", return_value=["/synthetic/a"]), \
                patch("app.settings.routes.active_session", return_value=self.session), \
                patch("app.settings.routes.audit_action"), \
                patch.object(adapter.index_job, "start", new_callable=AsyncMock) as index:
            response = self.client.post("/api/settings/folders/native-roots")
        self.assertEqual(response.status_code, 200)
        index.assert_not_awaited()

    def test_session_revocation_prevents_save(self) -> None:
        with patch("app.settings.routes.choose_folders", return_value=["/synthetic/a"]), \
                patch("app.settings.routes.active_session", side_effect=HTTPException(status_code=401)), \
                patch("app.settings.routes._apply", new_callable=AsyncMock) as apply:
            self.assertEqual(self.client.post("/api/settings/folders/native-roots").status_code, 401)
        self.app.state.settings_service.add_native_roots.assert_not_called()
        apply.assert_not_awaited()

    def test_unauthorized_role_and_remote_client_do_not_open_picker(self) -> None:
        with patch("app.settings.routes.choose_folders") as choose:
            self.app.dependency_overrides[current_session] = lambda: AuthenticatedSession("user", "s", "EMPLOYEE", "", "", "", False)
            self.assertEqual(self.client.post("/api/settings/folders/native-roots").status_code, 403)
            self.app.dependency_overrides[current_session] = lambda: self.session
            remote = TestClient(self.app, client=("192.0.2.1", 1234))
            self.assertEqual(remote.post("/api/settings/folders/native-roots").status_code, 403)
            choose.assert_not_called()

    def test_real_session_and_csrf_are_required(self) -> None:
        uri = "file:native_picker_auth_test?mode=memory&cache=shared"
        def connection():
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
                INSERT INTO users VALUES('owner', 'owner@example.test', 'Owner', 'ARCHIVE_OPERATOR', 'ACTIVE');
            """)
            settings = Settings(None, None, None, None, 43200, True, "http://127.0.0.1:3017")
            cookie = create_session(anchor, "owner", settings)
            self.app.state.settings = settings
            self.app.state.db_path = None
            self.app.dependency_overrides.clear()
            with patch("app.auth.authorization.connect", side_effect=lambda _: connection()), \
                    patch("app.settings.routes.choose_folders", return_value=[]) as choose:
                self.assertEqual(self.client.post("/api/settings/folders/native-roots").status_code, 401)
                self.client.cookies.set(SESSION_COOKIE, cookie)
                self.assertEqual(self.client.post("/api/settings/folders/native-roots").status_code, 403)
                self.assertEqual(self.client.post("/api/settings/folders/native-roots", headers={
                    "Origin": "http://127.0.0.1:3017",
                    "X-CSRF-Token": csrf_token(cookie.split(".", 1)[1]),
                }).status_code, 200)
                choose.assert_called_once()
        finally:
            anchor.close()
