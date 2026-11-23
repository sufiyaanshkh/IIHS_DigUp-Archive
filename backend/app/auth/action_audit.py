from __future__ import annotations

from fastapi import Request

from app.auth.authorization import AuthenticatedSession
from app.auth.database import connect
from app.auth.sessions import audit


def audit_action(request: Request, session: AuthenticatedSession, action: str) -> None:
    db = connect(request.app.state.db_path)
    try:
        audit(db, action, "SUCCESS", actor=session.user_id, request_id=request.state.request_id)
    finally:
        db.close()
