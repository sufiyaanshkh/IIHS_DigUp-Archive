from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from app.auth.database import connect
from app.core.config import Settings

SESSION_COOKIE = "__Host-iihs_session"


def utc_iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def audit(connection: sqlite3.Connection, action: str, outcome: str, *, actor: str | None = None,
          target: str | None = None, before: str | None = None, after: str | None = None,
          reason: str | None = None, request_id: str | None = None) -> None:
    connection.execute(
        "INSERT INTO audit_events(id, actor_user_id, target_user_id, action, timestamp, "
        "before_value, after_value, reason, request_id, outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), actor, target, action, utc_iso(), before, after, reason, request_id, outcome),
    )


def create_session(connection: sqlite3.Connection, user_id: str, settings: Settings) -> str:
    user = connection.execute("SELECT status FROM users WHERE id=?", (user_id,)).fetchone()
    if user is None or user["status"] != "ACTIVE":
        raise ValueError("only ACTIVE users may receive sessions")
    now = datetime.now(timezone.utc)
    sid = str(uuid.uuid4())
    secret = secrets.token_urlsafe(48)
    connection.execute(
        "INSERT INTO sessions(id,user_id,session_secret_hash,created_at,last_seen_at,expires_at) "
        "VALUES(?,?,?,?,?,?)",
        (sid, user_id, hashlib.sha256(secret.encode()).hexdigest(), utc_iso(now), utc_iso(now),
         utc_iso(now + timedelta(seconds=settings.session_max_age))),
    )
    return f"{sid}.{secret}"


def load_session(connection: sqlite3.Connection, cookie: str | None) -> tuple[sqlite3.Row, str] | None:
    if not cookie or "." not in cookie:
        return None
    sid, secret = cookie.split(".", 1)
    if len(secret) > 128:
        return None
    row = connection.execute(
        "SELECT s.id AS session_id, s.session_secret_hash, s.expires_at, s.revoked_at, "
        "u.id, u.email, u.display_name, u.role, u.status, "
        "COALESCE(c.must_change_password, 0) AS must_change_password FROM sessions s "
        "JOIN users u ON u.id=s.user_id LEFT JOIN local_credentials c ON c.user_id=u.id "
        "WHERE s.id=?", (sid,),
    ).fetchone()
    if row is None or row["revoked_at"] or row["expires_at"] <= utc_iso():
        return None
    if not hmac.compare_digest(row["session_secret_hash"], hashlib.sha256(secret.encode()).hexdigest()):
        return None
    if row["status"] != "ACTIVE":
        return None
    connection.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (utc_iso(), sid))
    return row, secret


def csrf_token(secret: str) -> str:
    return hmac.new(secret.encode(), b"iihs-auth-csrf-v1", hashlib.sha256).hexdigest()


def cookie_header(value: str, settings: Settings, *, max_age: int | None = None) -> str:
    parts = [f"{SESSION_COOKIE}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    if settings.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header(settings: Settings) -> str:
    return cookie_header("", settings, max_age=0)
