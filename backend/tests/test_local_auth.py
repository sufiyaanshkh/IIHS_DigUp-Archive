from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth.bootstrap_local import bootstrap, main as bootstrap_cli
from app.auth.database import connect, migrate
from app.auth.local import check_rate_limit
from app.core.config import Settings
from app.main import create_app


class LocalAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.db_path = str(Path(self.tmp.name) / "auth.sqlite")
        migrate(self.db_path)
        self.settings = Settings(None, None, None, None, 43200, True, "https://testserver", True)
        self.client = TestClient(create_app(self.settings, self.db_path), base_url="https://testserver")
        self.origin = {"origin": "https://testserver"}

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def test_bootstrap_is_one_time_and_local_login_uses_existing_session(self) -> None:
        db = connect(self.db_path)
        db.execute(
            "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
            "VALUES('existing','tenant','object','admin@example.org','Existing','EMPLOYEE','ACTIVE','t','t')"
        )
        db.close()
        user = bootstrap(self.db_path, "admin@example.org", "Admin Person", "A long synthetic password 8")
        with self.assertRaisesRegex(ValueError, "already been completed"):
            bootstrap(self.db_path, "other@example.org", "Other Person", "Another synthetic password 9")
        with closing(sqlite3.connect(self.db_path)) as db, db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM users WHERE id=?", (user,))
        response = self.client.post("/auth/local/login", headers=self.origin, json={
            "email": "ADMIN@example.org", "password": "A long synthetic password 8",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["password_change_required"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        profile = self.client.get("/auth/session")
        self.assertEqual((profile.json()["id"], profile.json()["role"]), (user, "SUPER_ADMIN"))
        with closing(sqlite3.connect(self.db_path)) as db, db:
            stored = db.execute("SELECT password_hash FROM local_credentials").fetchone()[0]
            self.assertTrue(stored.startswith("$argon2id$"))
            self.assertNotIn("synthetic password", stored)
            self.assertEqual(db.execute("SELECT role FROM users WHERE id='existing'").fetchone(), ("EMPLOYEE",))
        self.assertEqual(self.client.post("/auth/local/login", headers=self.origin, json={
            "email": "admin@example.org", "password": "incorrect password",
        }).status_code, 401)

    def test_registration_is_off_until_enabled_and_never_accepts_role(self) -> None:
        body = {"display_name": "Employee", "email": "user@example.org", "password": "A long synthetic password 8"}
        self.assertEqual(self.client.post("/auth/local/register", headers=self.origin, json=body).status_code, 403)
        db = connect(self.db_path)
        db.execute("UPDATE auth_configuration SET registration_enabled=1")
        db.close()
        self.assertEqual(self.client.post("/auth/local/register", headers=self.origin, json={**body, "role": "SUPER_ADMIN"}).status_code, 422)
        oversized = "SensitiveExample123!" * 10
        invalid = self.client.post("/auth/local/login", headers=self.origin, json={"email": "user@example.org", "password": oversized})
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(oversized, invalid.text)
        self.assertEqual(self.client.post("/auth/local/register", headers={"origin": "https://evil.example"}, json=body).status_code, 403)
        self.assertEqual(self.client.post("/auth/local/register", headers=self.origin,
                                          json={**body, "password": "aaaaaaaaaaaa"}).status_code, 422)
        self.assertEqual(self.client.post("/auth/local/register", headers=self.origin, json=body).status_code, 201)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT role FROM users").fetchone(), ("EMPLOYEE",))

    def test_fresh_application_denies_anonymous_management_and_registration_deployment_cap(self) -> None:
        settings = Settings(None, None, None, None, 43200, True, "https://testserver")
        db = connect(self.db_path)
        db.execute("UPDATE auth_configuration SET registration_enabled=1")
        db.close()
        with TestClient(create_app(settings, self.db_path), base_url="https://testserver") as client:
            for path in ("/api/health", "/api/settings", "/api/indexing/status", "/api/admin/users", "/api/admin/audit"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 401)
            self.assertFalse(client.get("/auth/local/registration").json()["enabled"])
            self.assertEqual(client.post("/auth/local/register", headers=self.origin, json={
                "email": "new@example.org", "display_name": "New User", "password": "Synthetic registration 8!",
            }).status_code, 403)

    def test_cli_bootstrap_and_rate_limit(self) -> None:
        with patch("sys.argv", ["bootstrap_local", "--db", self.db_path]), \
                patch("builtins.input", side_effect=["Synthetic Admin", "synthetic@example.org"]), \
                patch("getpass.getpass", side_effect=["Synthetic credential 8!", "Synthetic credential 8!"]), \
                patch("builtins.print") as output:
            self.assertEqual(bootstrap_cli(), 0)
        self.assertNotIn("Synthetic credential 8!", str(output.call_args_list))
        db = connect(self.db_path)
        try:
            self.assertEqual([check_rate_limit(db, "test", "synthetic-client") for _ in range(21)],
                             [True] * 20 + [False])
        finally:
            db.close()

    def test_bootstrap_module_entrypoint(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.auth.bootstrap_local", "--help"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--db", result.stdout)

    def test_role_management_and_temporary_password_enforcement(self) -> None:
        super_id = bootstrap(self.db_path, "super@example.org", "Super Admin", "A long synthetic password 8")
        response = self.client.post("/auth/local/login", headers=self.origin, json={
            "email": "super@example.org", "password": "A long synthetic password 8",
        })
        self.assertEqual(response.status_code, 200)
        csrf = self.client.get("/auth/session").headers["x-csrf-token"]
        headers = {**self.origin, "x-csrf-token": csrf}
        ids = {}
        for role in ("ADMIN", "ARCHIVE_OPERATOR", "EMPLOYEE"):
            result = self.client.post("/api/admin/users", headers=headers, json={
                "email": f"{role.lower()}@example.org", "display_name": f"Test {role}",
                "role": role, "temporary_password": "Temporary synthetic password 8",
            })
            self.assertEqual(result.status_code, 201, result.text)
            ids[role] = result.json()["id"]
        blocked = self.client.patch(f"/api/admin/users/{super_id}", headers=headers, json={"status": "DEACTIVATED"})
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(self.client.patch(f"/api/admin/users/{ids['EMPLOYEE']}", headers=headers,
                                           json={"role": "ARCHIVE_OPERATOR"}).status_code, 200)
        self.assertEqual(self.client.put("/api/admin/registration", headers=headers, json={"enabled": True}).status_code, 200)
        self.assertTrue(self.client.get("/auth/local/registration").json()["enabled"])
        self.assertEqual(self.client.get("/api/admin/audit").status_code, 200)

        with TestClient(create_app(self.settings, self.db_path), base_url="https://testserver") as admin:
            login = admin.post("/auth/local/login", headers=self.origin, json={
                "email": "admin@example.org", "password": "Temporary synthetic password 8",
            })
            self.assertTrue(login.json()["password_change_required"])
            self.assertEqual(admin.get("/api/health").status_code, 403)
            admin_csrf = admin.get("/auth/session").headers["x-csrf-token"]
            admin_headers = {**self.origin, "x-csrf-token": admin_csrf}
            self.assertEqual(admin.post("/auth/local/change-password", headers=admin_headers, json={
                "current_password": "Temporary synthetic password 8",
                "new_password": "Temporary synthetic password 8",
            }).status_code, 422)
            self.assertEqual(admin.post("/auth/local/change-password", headers=admin_headers, json={
                "current_password": "Temporary synthetic password 8",
                "new_password": "Replacement synthetic password 9",
            }).status_code, 204)
            self.assertEqual(admin.get("/api/admin/users").status_code, 200)
            for target in (super_id, ids["ADMIN"]):
                result = admin.patch(f"/api/admin/users/{target}", headers=admin_headers,
                                     json={"status": "DEACTIVATED"})
                self.assertEqual(result.status_code, 403)
                self.assertEqual(admin.patch(f"/api/admin/users/{target}", headers=admin_headers,
                                             json={"role": "EMPLOYEE"}).status_code, 403)
            self.assertEqual(admin.post("/api/admin/users", headers=admin_headers, json={
                "email": "another@example.org", "display_name": "Another Admin",
                "role": "ADMIN", "temporary_password": "Temporary synthetic password 8",
            }).status_code, 403)
            self.assertEqual(admin.get("/api/admin/audit").status_code, 403)
            self.assertEqual(admin.put("/api/admin/registration", headers=admin_headers,
                                       json={"enabled": False}).status_code, 403)
            created = admin.post("/api/admin/users", headers=admin_headers, json={
                "email": "operator2@example.org", "display_name": "Second Operator",
                "role": "ARCHIVE_OPERATOR", "temporary_password": "Temporary synthetic password 8",
            })
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(admin.post(f"/api/admin/users/{super_id}/temporary-password", headers=admin_headers, json={
                "temporary_password": "Reset synthetic password 7",
            }).status_code, 403)
            self.assertEqual(self.client.patch(f"/api/admin/users/{ids['ADMIN']}", headers=headers,
                                               json={"status": "DEACTIVATED"}).status_code, 200)
            self.assertEqual(admin.get("/auth/session").status_code, 401)
            self.assertEqual(admin.post("/auth/local/login", headers=self.origin, json={
                "email": "admin@example.org", "password": "Replacement synthetic password 9",
            }).status_code, 401)
        self.assertEqual(self.client.patch(f"/api/admin/users/{ids['ADMIN']}", headers=headers,
                                           json={"status": "ACTIVE"}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/admin/users/{ids['ADMIN']}/temporary-password", headers=headers, json={
            "temporary_password": "Reset synthetic password 7",
        }).status_code, 200)
        with TestClient(create_app(self.settings, self.db_path), base_url="https://testserver") as admin:
            login = admin.post("/auth/local/login", headers=self.origin, json={
                "email": "admin@example.org", "password": "Reset synthetic password 7",
            })
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json()["password_change_required"])
        with closing(sqlite3.connect(self.db_path)) as db:
            log = str(db.execute("SELECT action,before_value,after_value,reason FROM audit_events").fetchall())
            self.assertNotIn("Temporary synthetic password 8", log)
            self.assertNotIn("Reset synthetic password 7", log)
        self.assertEqual(self.client.patch(f"/api/admin/users/{ids['EMPLOYEE']}", headers=headers,
                                           json={"role": "EMPLOYEE"}).status_code, 200)
        with TestClient(create_app(self.settings, self.db_path), base_url="https://testserver") as employee:
            self.assertEqual(employee.post("/auth/local/login", headers=self.origin, json={
                "email": "employee@example.org", "password": "Temporary synthetic password 8",
            }).status_code, 200)
            employee_csrf = employee.get("/auth/session").headers["x-csrf-token"]
            employee_headers = {**self.origin, "x-csrf-token": employee_csrf}
            self.assertEqual(employee.post("/auth/local/change-password", headers=employee_headers, json={
                "current_password": "Temporary synthetic password 8",
                "new_password": "Replacement synthetic password 9",
            }).status_code, 204)
            self.assertEqual(employee.get("/api/admin/users").status_code, 403)
            self.assertEqual(employee.get("/api/settings").status_code, 403)
            self.assertEqual(employee.post("/api/indexing/sync", headers=employee_headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()
