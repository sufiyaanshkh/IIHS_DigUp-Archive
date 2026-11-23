from __future__ import annotations

import hashlib
import json
import logging
import secrets
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.database import connect
from app.core.config import Settings

FLOW_COOKIE_PREFIX = "__Host-iihs_oidc_"
FLOW_TTL_SECONDS = 600
FLOW_STATE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def validate_member_claims(claims: dict[str, Any], tenant_id: str) -> tuple[str, str, str, str]:
    """Return tenant, object, email and display name only for configured internal members."""
    try:
        expected_tenant = str(uuid.UUID(tenant_id))
        claim_tenant = str(uuid.UUID(claims.get("tid", "")))
        oid = str(uuid.UUID(claims.get("oid", "")))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid_identity") from exc
    if claim_tenant != expected_tenant:
        raise ValueError("tenant_mismatch")
    acct = claims.get("acct")
    if acct not in (0, "0") or isinstance(acct, bool):
        raise ValueError("ineligible_identity")
    email = claims.get("email") or claims.get("preferred_username")
    display_name = claims.get("name")
    if not isinstance(email, str) or not email or not isinstance(display_name, str) or not display_name:
        raise ValueError("missing_profile_claims")
    return expected_tenant, oid, email, display_name


class OIDCFlowSessionMiddleware:
    """Keep Authlib state, nonce and PKCE verifier server-side in SQLite."""

    def __init__(self, app: ASGIApp, settings: Settings, db_path: str | None = None):
        self.app = app
        self.settings = settings
        self.db_path = db_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/auth/microsoft/"):
            await self.app(scope, receive, send)
            return

        is_start = scope["path"].endswith("/start")
        query = parse_qs(scope.get("query_string", b"").decode("ascii", errors="ignore"))
        callback_state = query.get("state", [""])[0]
        if is_start:
            flow_cookie_name = ""
        elif FLOW_STATE.fullmatch(callback_state):
            flow_cookie_name = FLOW_COOKIE_PREFIX + callback_state
        else:
            flow_cookie_name = ""
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("latin1")
        cookies = {part.strip().split("=", 1)[0]: part.strip().split("=", 1)[1]
                   for part in cookie_header.split(";") if "=" in part}
        flow_secret = cookies.get(flow_cookie_name) if flow_cookie_name else None
        if not flow_secret or len(flow_secret) > 128:
            flow_secret = secrets.token_urlsafe(32)
        flow_hash = hashlib.sha256(flow_secret.encode()).hexdigest()
        session: dict[str, Any] = {}
        connection = connect(self.db_path)
        try:
            row = connection.execute(
                "SELECT flow_data, expires_at FROM oidc_flow_sessions WHERE flow_secret_hash=?",
                (flow_hash,),
            ).fetchone()
            if row and row["expires_at"] > iso_now():
                try:
                    session = json.loads(row["flow_data"])
                except (TypeError, json.JSONDecodeError):
                    session = {}
        finally:
            connection.close()
        scope["session"] = session
        response_started = False

        async def send_with_flow(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start" and not response_started:
                response_started = True
                if is_start:
                    state_key = next((key for key in session if key.startswith("_state_microsoft_")), "")
                    new_state = state_key.removeprefix("_state_microsoft_")
                    response_cookie_name = FLOW_COOKIE_PREFIX + new_state if FLOW_STATE.fullmatch(new_state) else ""
                else:
                    response_cookie_name = flow_cookie_name
                db = connect(self.db_path)
                try:
                    db.execute("DELETE FROM oidc_flow_sessions WHERE expires_at <= ?", (iso_now(),))
                    if session:
                        now = utc_now()
                        db.execute(
                            "INSERT INTO oidc_flow_sessions(flow_secret_hash, flow_data, created_at, expires_at) "
                            "VALUES(?,?,?,?) ON CONFLICT(flow_secret_hash) DO UPDATE SET "
                            "flow_data=excluded.flow_data, expires_at=excluded.expires_at",
                            (flow_hash, json.dumps(session, separators=(",", ":")),
                             now.isoformat(timespec="seconds"),
                             (now + timedelta(seconds=FLOW_TTL_SECONDS)).isoformat(timespec="seconds")),
                        )
                    else:
                        db.execute("DELETE FROM oidc_flow_sessions WHERE flow_secret_hash=?", (flow_hash,))
                finally:
                    db.close()
                response_headers = list(message.get("headers", []))
                if session and response_cookie_name:
                    cookie = (f"{response_cookie_name}={flow_secret}; Path=/; Max-Age={FLOW_TTL_SECONDS}; "
                              f"HttpOnly; SameSite=Lax" + ("; Secure" if self.settings.cookie_secure else ""))
                elif response_cookie_name:
                    cookie = (f"{response_cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" +
                              ("; Secure" if self.settings.cookie_secure else ""))
                if response_cookie_name:
                    response_headers.append((b"set-cookie", cookie.encode("latin1")))
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_flow)


def build_oauth(settings: Settings):
    from authlib.integrations.starlette_client import OAuth

    # Authlib logs the generated PKCE verifier at DEBUG; never let app debug settings expose it.
    logging.getLogger("authlib.integrations.base_client.sync_app").setLevel(logging.INFO)
    oauth = OAuth()
    if settings.entra_ready:
        oauth.register(
            name="microsoft",
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            server_metadata_url=(
                f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0/"
                ".well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )
    return oauth
