from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from app.auth.database import connect
from app.auth.sessions import audit


class LoginRejected(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def authenticate_member(db_path: str | None, tenant_id: str, object_id: str,
                        email: str, display_name: str, request_id: str | None) -> sqlite3.Row:
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM users WHERE entra_tenant_id=? AND entra_object_id=?",
            (tenant_id, object_id),
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if row is None:
            user_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at,last_login_at) "
                "VALUES(?,?,?,?,?,'EMPLOYEE','ACTIVE',?,?,?)",
                (user_id, tenant_id, object_id, email, display_name, now, now, now),
            )
            audit(connection, "user.provisioned", "SUCCESS", target=user_id,
                  after='{"role":"EMPLOYEE","status":"ACTIVE"}',
                  reason="entra_internal_member", request_id=request_id)
        else:
            user_id = row["id"]
            if row["status"] != "ACTIVE":
                raise LoginRejected("inactive_account")
            connection.execute(
                "UPDATE users SET email=?,display_name=?,updated_at=?,last_login_at=? WHERE id=?",
                (email, display_name, now, now, user_id),
            )
        if row is None or row["status"] == "ACTIVE":
            audit(connection, "authentication.succeeded", "SUCCESS", actor=user_id, target=user_id,
                  request_id=request_id)
        result = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def audit_failure(db_path: str | None, reason: str, request_id: str | None) -> None:
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        audit(connection, "authentication.failed", "FAILURE", reason=reason, request_id=request_id)
        connection.commit()
    finally:
        connection.close()
