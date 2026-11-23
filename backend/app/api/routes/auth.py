from __future__ import annotations

import hmac
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.responses import RedirectResponse

from app.auth.database import connect
from app.auth.oidc import build_oauth, validate_member_claims
from app.auth.repository import LoginRejected, audit_failure, authenticate_member
from app.auth.sessions import (
    SESSION_COOKIE, audit, clear_cookie_header, cookie_header, create_session,
    csrf_token, load_session, utc_iso,
)
from app.core.config import Settings

router = APIRouter(prefix="/auth")


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _oauth(request: Request):
    return request.app.state.oauth


def _request_id(request: Request) -> str:
    return request.state.request_id


def _login_redirect(request: Request, *, error: str | None = None) -> RedirectResponse:
    settings = _settings(request)
    base = settings.public_origin.rstrip("/") if settings.public_origin else ""
    query = f"?{urlencode({'error': error})}" if error else ""
    return RedirectResponse(f"{base}/{query}", status_code=303)


@router.get("/microsoft/start")
async def microsoft_start(request: Request):
    settings = _settings(request)
    if not settings.entra_ready:
        raise HTTPException(status_code=503, detail="Microsoft sign-in is not configured")
    try:
        return await _oauth(request).microsoft.authorize_redirect(request, settings.redirect_uri)
    except Exception:
        audit_failure(request.app.state.db_path, "oidc_start_failed", _request_id(request))
        return _login_redirect(request, error="sign_in_unavailable")


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request):
    settings = _settings(request)
    if not settings.entra_ready:
        raise HTTPException(status_code=503, detail="Microsoft sign-in is not configured")
    try:
        token = await _oauth(request).microsoft.authorize_access_token(request)
        claims = token.get("userinfo")
        if claims is None:
            raise ValueError("missing_id_token")
        tenant, object_id, email, display_name = validate_member_claims(dict(claims), settings.tenant_id or "")
        user = authenticate_member(request.app.state.db_path, tenant, object_id,
                                   email, display_name, _request_id(request))
        connection = connect(request.app.state.db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cookie_value = create_session(connection, user["id"], settings)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        base = settings.public_origin.rstrip("/") if settings.public_origin else ""
        redirect = RedirectResponse(f"{base}/archive", status_code=303)
        redirect.headers.append("set-cookie", cookie_header(cookie_value, settings,
                                                              max_age=settings.session_max_age))
        # Authlib's temporary state cookie is cleared by its flow middleware.
        return redirect
    except LoginRejected as exc:
        audit_failure(request.app.state.db_path, exc.reason, _request_id(request))
    except Exception as exc:
        reason = exc.args[0] if isinstance(exc, ValueError) and exc.args else "oidc_callback_failed"
        if reason not in {"tenant_mismatch", "ineligible_identity", "invalid_identity", "missing_profile_claims"}:
            reason = "oidc_callback_failed"
        audit_failure(request.app.state.db_path, reason, _request_id(request))
    return _login_redirect(request, error="sign_in_failed")


@router.get("/session")
def session_info(request: Request, response: Response):
    connection = connect(request.app.state.db_path)
    try:
        loaded = load_session(connection, request.cookies.get(SESSION_COOKIE))
        if loaded is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user, secret = loaded
        response.headers["X-CSRF-Token"] = csrf_token(secret)
        return {**{key: user[key] for key in ("id", "display_name", "email", "role", "status")},
                "password_change_required": bool(user["must_change_password"])}
    finally:
        connection.close()


@router.post("/logout")
def logout(request: Request, response: Response):
    settings = _settings(request)
    origin = request.headers.get("origin")
    expected = settings.public_origin.rstrip("/") if settings.public_origin else str(request.base_url).rstrip("/")
    if not origin or origin.rstrip("/") != expected:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    connection = connect(request.app.state.db_path)
    try:
        loaded = load_session(connection, request.cookies.get(SESSION_COOKIE))
        if loaded is not None:
            user, secret = loaded
            supplied = request.headers.get("x-csrf-token", "")
            if not supplied or not hmac.compare_digest(supplied, csrf_token(secret)):
                raise HTTPException(status_code=403, detail="Invalid CSRF token")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE sessions SET revoked_at=?, revoked_by=?, revocation_reason=? "
                "WHERE id=? AND revoked_at IS NULL",
                (utc_iso(), user["id"], "logout", user["session_id"]),
            )
            audit(connection, "session.revoked", "SUCCESS", actor=user["id"],
                  target=user["id"], reason="logout", request_id=_request_id(request))
            connection.commit()
        response.status_code = 204
        response.headers.append("set-cookie", clear_cookie_header(settings))
        return response
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def register_oauth(app, settings: Settings) -> None:
    app.state.oauth = build_oauth(settings)
