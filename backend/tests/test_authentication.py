from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from authlib.oidc.core import CodeIDToken
from fastapi.testclient import TestClient

from app.auth.database import connect, migrate
from app.auth.oidc import validate_member_claims
from app.auth.repository import authenticate_member
from app.auth.sessions import SESSION_COOKIE, create_session, load_session
from app.core.config import Settings
from app.main import CallbackQueryRedactionFilter, create_app


class FakeMicrosoft:
    def __init__(self):
        self.expected_state = "state-123"
        self.expected_nonce = "nonce-456"

    async def authorize_redirect(self, request, redirect_uri):
        request.session["_state_microsoft_state-123"] = {
            "data": {"nonce": self.expected_nonce, "code_verifier": "verifier"}
        }
        from starlette.responses import RedirectResponse
        return RedirectResponse(
            "https://login.microsoftonline.com/authorize?" +
            "state=state-123&nonce=nonce-456&code_challenge=challenge", status_code=302
        )

    async def authorize_access_token(self, request):
        entry = request.session.get("_state_microsoft_state-123")
        if request.query_params.get("state") != self.expected_state or not entry:
            raise ValueError("state_mismatch")
        if entry["data"].get("nonce") != self.expected_nonce:
            raise ValueError("nonce_mismatch")
        request.session.pop("_state_microsoft_state-123")
        return {"userinfo": {
            "tid": "11111111-1111-4111-8111-111111111111",
            "oid": "22222222-2222-4222-8222-222222222222", "acct": "0",
            "email": "member@iihs.ac.in", "name": "IIHS Member",
        }}


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.db_path = str(Path(self.tmp.name) / "auth.sqlite")
        migrate(self.db_path)
        self.settings = Settings("11111111-1111-4111-8111-111111111111", "client-id", "client-secret",
                                 "https://archive.example/auth/microsoft/callback",
                                 43200, True, "https://testserver")
        self.app = create_app(self.settings, self.db_path)
        self.app.state.oauth.microsoft = FakeMicrosoft()
        self.client = TestClient(self.app, base_url="https://testserver")

    def tearDown(self) -> None:
        self.client.close()
        self.tmp.cleanup()

    def user(self, *, user_id: str = "u1", oid: str = "object-id",
             role: str = "EMPLOYEE", status: str = "ACTIVE") -> str:
        db = connect(self.db_path)
        try:
            db.execute(
                "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                "VALUES(?,?,?,?,'IIHS Member',?,?, 't','t')",
                (user_id, self.settings.tenant_id, oid, f"{user_id}@iihs.ac.in", role, status),
            )
            return user_id
        finally:
            db.close()

    def test_oidc_start_keeps_state_nonce_and_pkce_verifier_server_side(self) -> None:
        response = self.client.get("/auth/microsoft/start", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("state=state-123", response.headers["location"])
        self.assertIn("nonce=nonce-456", response.headers["location"])
        self.assertIn("code_challenge=challenge", response.headers["location"])
        cookie = response.cookies.get("__Host-iihs_oidc_state-123")
        self.assertTrue(cookie)
        db = connect(self.db_path)
        try:
            row = db.execute("SELECT flow_secret_hash,flow_data FROM oidc_flow_sessions").fetchone()
            self.assertEqual(row["flow_secret_hash"], hashlib.sha256(cookie.encode()).hexdigest())
            self.assertNotIn(cookie, row["flow_data"])
            self.assertIn("nonce-456", row["flow_data"])
            self.assertIn("verifier", row["flow_data"])
        finally:
            db.close()

    def test_oidc_callback_checks_saved_state_nonce_then_provisions_employee(self) -> None:
        start = self.client.get("/auth/microsoft/start", follow_redirects=False)
        callback = self.client.get("/auth/microsoft/callback?code=fake&state=state-123",
                                  cookies=start.cookies, follow_redirects=False)
        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers["location"], "https://testserver/archive")
        self.assertIn("__Host-iihs_session", callback.headers["set-cookie"])
        self.assertIn("Secure", callback.headers["set-cookie"])
        self.assertIn("HttpOnly", callback.headers["set-cookie"])
        self.assertIn("SameSite=Lax", callback.headers["set-cookie"])
        db = connect(self.db_path)
        try:
            user = db.execute("SELECT role,status FROM users WHERE entra_object_id='22222222-2222-4222-8222-222222222222'").fetchone()
            self.assertEqual(tuple(user), ("EMPLOYEE", "ACTIVE"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events WHERE action='user.provisioned'").fetchone()[0], 1)
        finally:
            db.close()

    def test_callback_rejects_missing_or_mismatched_state(self) -> None:
        response = self.client.get("/auth/microsoft/callback?code=fake&state=wrong",
                                   follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("sign_in_failed", response.headers["location"])

    def test_tenant_mismatch_guest_and_missing_member_claim_are_rejected(self) -> None:
        base = {"tid": self.settings.tenant_id, "oid": "22222222-2222-4222-8222-222222222222", "acct": "0",
                "email": "member@iihs.ac.in", "name": "Member"}
        with self.assertRaisesRegex(ValueError, "tenant_mismatch"):
            validate_member_claims({**base, "tid": "33333333-3333-4333-8333-333333333333"}, self.settings.tenant_id)
        with self.assertRaisesRegex(ValueError, "ineligible_identity"):
            validate_member_claims({**base, "acct": "1"}, self.settings.tenant_id)
        with self.assertRaisesRegex(ValueError, "ineligible_identity"):
            validate_member_claims({key: value for key, value in base.items() if key != "acct"}, self.settings.tenant_id)

    def test_authlib_oidc_claim_validation_rejects_wrong_nonce(self) -> None:
        import time

        now = int(time.time())
        token = CodeIDToken(
            {"iss": "issuer", "sub": "subject", "aud": "client", "exp": now + 60,
             "iat": now, "nonce": "wrong"},
            {"alg": "RS256"},
            params={"nonce": "expected", "client_id": "client"},
        )
        with self.assertRaises(Exception):
            token.validate(now=now)

    def test_callback_access_log_query_is_redacted(self) -> None:
        import logging

        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s", (), None)
        record.args = ("127.0.0.1", "GET", "/auth/microsoft/callback?code=secret&state=secret", "1.1", 302)
        self.assertTrue(CallbackQueryRedactionFilter().filter(record))
        self.assertNotIn("secret", str(record.args))

    def test_new_member_is_employee_and_existing_role_and_status_are_preserved(self) -> None:
        new = authenticate_member(self.db_path, self.settings.tenant_id, "33333333-3333-4333-8333-333333333333", "a@iihs.ac.in", "A", "req")
        self.assertEqual((new["role"], new["status"]), ("EMPLOYEE", "ACTIVE"))
        self.user(role="REVIEWER", status="ACTIVE")
        existing = authenticate_member(self.db_path, self.settings.tenant_id, "object-id", "updated@iihs.ac.in", "Updated", "req")
        self.assertEqual((existing["role"], existing["status"], existing["email"]),
                         ("REVIEWER", "ACTIVE", "updated@iihs.ac.in"))
        self.user(user_id="u2", oid="object-2", role="REVIEWER", status="SUSPENDED")
        db = connect(self.db_path)
        try:
            with self.assertRaisesRegex(ValueError, "inactive_account"):
                authenticate_member(self.db_path, self.settings.tenant_id, "object-2", "new@iihs.ac.in", "Name", "req")
            row = db.execute("SELECT role,status FROM users WHERE id='u2'").fetchone()
            self.assertEqual(tuple(row), ("REVIEWER", "SUSPENDED"))
        finally:
            db.close()

    def test_session_secret_is_hashed_expiry_enforced_and_revocation_works(self) -> None:
        self.user()
        db = connect(self.db_path)
        try:
            cookie = create_session(db, "u1", self.settings)
            db.commit()
            sid, raw = cookie.split(".", 1)
            stored = db.execute("SELECT session_secret_hash FROM sessions WHERE id=?", (sid,)).fetchone()[0]
            self.assertEqual(stored, hashlib.sha256(raw.encode()).hexdigest())
            self.assertNotEqual(stored, raw)
            self.assertIsNotNone(load_session(db, cookie))
            db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (sid,))
            self.assertIsNone(load_session(db, cookie))
            db.execute("UPDATE sessions SET expires_at='2999-01-01T00:00:00+00:00',revoked_at='t' WHERE id=?", (sid,))
            self.assertIsNone(load_session(db, cookie))
        finally:
            db.close()

    def test_session_creation_rejects_inactive_accounts(self) -> None:
        self.user(status="LOCKED")
        db = connect(self.db_path)
        try:
            with self.assertRaisesRegex(ValueError, "ACTIVE"):
                create_session(db, "u1", self.settings)
        finally:
            db.close()

    def test_inactive_user_cannot_load_session_and_logout_revokes_active_session(self) -> None:
        self.user()
        db = connect(self.db_path)
        cookie = create_session(db, "u1", self.settings)
        db.commit()
        db.close()
        session = self.client.get("/auth/session", cookies={SESSION_COOKIE: cookie})
        self.assertEqual(session.status_code, 200)
        csrf = session.headers["x-csrf-token"]
        rejected_logout = self.client.post("/auth/logout", cookies={SESSION_COOKIE: cookie},
                                           headers={"origin": "https://testserver", "x-csrf-token": "wrong"})
        self.assertEqual(rejected_logout.status_code, 403)
        logout = self.client.post("/auth/logout", cookies={SESSION_COOKIE: cookie},
                                  headers={"origin": "https://testserver", "x-csrf-token": csrf})
        self.assertEqual(logout.status_code, 204)
        db = connect(self.db_path)
        try:
            self.assertIsNotNone(db.execute("SELECT revoked_at FROM sessions").fetchone()[0])
            self.assertEqual(db.execute("SELECT action FROM audit_events ORDER BY timestamp DESC LIMIT 1").fetchone()[0],
                             "session.revoked")
        finally:
            db.close()
        db = connect(self.db_path)
        try:
            active_cookie = create_session(db, "u1", self.settings)
            db.execute("UPDATE users SET status='LOCKED' WHERE id='u1'")
            db.commit()
            self.assertIsNone(load_session(db, active_cookie))
        finally:
            db.close()

    def test_session_response_contains_only_safe_profile_fields(self) -> None:
        self.user()
        db = connect(self.db_path)
        cookie = create_session(db, "u1", self.settings)
        db.commit()
        db.close()
        response = self.client.get("/auth/session", cookies={SESSION_COOKIE: cookie})
        self.assertEqual(set(response.json()), {"id", "display_name", "email", "role", "status", "password_change_required"})

    def test_archive_and_settings_apis_require_active_authorized_sessions(self) -> None:
        requests = [
            ("get", "/api/health", None),
            ("get", "/api/engine/status", None),
            ("post", "/api/search", {"query": "archive"}),
            ("get", "/api/indexing/status", None),
            ("post", "/api/indexing/sync", None),
            ("post", "/api/indexing/stop", None),
            ("get", "/api/media/opaque-handle", None),
            ("get", "/api/media/opaque-handle/image-metadata", None),
            ("get", "/api/media/opaque-handle/preview", None),
            ("get", "/api/media/opaque-handle/frame?at=1", None),
            ("get", "/api/media/opaque-handle/download", None),
            ("get", "/api/settings", None),
            ("get", "/api/settings/volumes", None),
            ("get", "/api/settings/browse?volume_ref=opaque", None),
            ("put", "/api/settings/folders/extensions", {"extensions": []}),
        ]
        for method, path, body in requests:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, json=body) if body is not None else getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 401, response.text)

        self.user(role="EMPLOYEE")
        db = connect(self.db_path)
        cookie = create_session(db, "u1", self.settings)
        db.commit()
        db.close()
        self.client.cookies.set(SESSION_COOKIE, cookie)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/media/opaque-handle").status_code, 404)
        self.assertEqual(self.client.get("/api/indexing/status").status_code, 403)
        self.assertEqual(self.client.get("/api/settings").status_code, 403)


if __name__ == "__main__":
    unittest.main()
