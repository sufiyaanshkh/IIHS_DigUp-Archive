from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.auth.database import connect
from app.auth.sessions import SESSION_COOKIE, csrf_token, load_session


@dataclass(frozen=True)
class AuthenticatedSession:
    user_id: str
    session_id: str
    role: str
    email: str
    display_name: str
    csrf: str
    must_change_password: bool


def active_session(request: Request) -> AuthenticatedSession:
    connection = connect(request.app.state.db_path)
    try:
        loaded = load_session(connection, request.cookies.get(SESSION_COOKIE))
        if loaded is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        user, secret = loaded
        return AuthenticatedSession(
            user_id=user["id"],
            session_id=user["session_id"],
            role=user["role"],
            email=user["email"],
            display_name=user["display_name"],
            csrf=csrf_token(secret),
            must_change_password=bool(user["must_change_password"]),
        )
    finally:
        connection.close()


def current_session(session: AuthenticatedSession = Depends(active_session)) -> AuthenticatedSession:
    if session.must_change_password:
        raise HTTPException(status_code=403, detail="Password change required")
    return session


def require_roles(*roles: str):
    def check(session: AuthenticatedSession = Depends(current_session)) -> AuthenticatedSession:
        if session.role not in roles:
            raise HTTPException(status_code=403, detail="You are not allowed to perform this operation")
        return session

    return check


def require_csrf(
    request: Request,
    session: AuthenticatedSession = Depends(active_session),
) -> None:
    settings = request.app.state.settings
    expected_origin = settings.public_origin.rstrip("/") if settings.public_origin else str(request.base_url).rstrip("/")
    origin = request.headers.get("origin", "").rstrip("/")
    supplied = request.headers.get("x-csrf-token", "")
    if not origin or origin != expected_origin or not supplied or not hmac.compare_digest(supplied, session.csrf):
        raise HTTPException(status_code=403, detail="Invalid request origin or CSRF token")
