from __future__ import annotations

import hmac
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.authorization import AuthenticatedSession, active_session, require_csrf
from app.auth.database import connect
from app.auth.local import check_rate_limit, create_local_user, hash_password, normalize_email, verify_password
from app.auth.sessions import audit, cookie_header, create_session, utc_iso

router = APIRouter(prefix="/auth/local")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class RegisterBody(LoginBody):
    display_name: str = Field(min_length=2, max_length=120)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


def _origin(request: Request) -> None:
    config = request.app.state.settings
    expected = config.public_origin.rstrip("/") if config.public_origin else str(request.base_url).rstrip("/")
    if request.headers.get("origin", "").rstrip("/") != expected:
        raise HTTPException(status_code=403, detail="Invalid request origin")


def _limit(db: sqlite3.Connection, request: Request, category: str) -> None:
    if not request.client or not check_rate_limit(db, category, request.client.host):
        raise HTTPException(status_code=429, detail="Too many attempts; try again later")


@router.get("/registration")
def registration_status(request: Request):
    db = connect(request.app.state.db_path)
    try:
        enabled = db.execute("SELECT registration_enabled FROM auth_configuration WHERE id=1").fetchone()[0]
        return {"enabled": bool(enabled and request.app.state.settings.demo_registration_allowed)}
    finally:
        db.close()


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request):
    _origin(request)
    db = connect(request.app.state.db_path)
    try:
        _limit(db, request, "register")
        try:
            password_hash = hash_password(body.password)
            db.execute("BEGIN IMMEDIATE")
            enabled = db.execute("SELECT registration_enabled FROM auth_configuration WHERE id=1").fetchone()[0]
            if not enabled or not request.app.state.settings.demo_registration_allowed:
                db.rollback()
                raise HTTPException(status_code=403, detail="Registration is not enabled")
            create_local_user(db, email=body.email, display_name=body.display_name, password_hash=password_hash,
                              role="EMPLOYEE", must_change_password=False, actor=None,
                              request_id=request.state.request_id)
            db.commit()
        except ValueError as exc:
            if db.in_transaction:
                db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Account could not be created") from exc
        return {"message": "Account created. Sign in to continue."}
    finally:
        db.close()


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    _origin(request)
    db = connect(request.app.state.db_path)
    try:
        _limit(db, request, "login")
        try:
            email = normalize_email(body.email)
        except ValueError:
            email = ""
        row = db.execute(
            "SELECT c.user_id,c.password_hash,c.must_change_password,u.status FROM local_credentials c "
            "JOIN users u ON u.id=c.user_id WHERE c.email_normalized=?", (email,),
        ).fetchone()
        valid = verify_password(row["password_hash"] if row else None, body.password)
        if not row or not valid or row["status"] != "ACTIVE":
            audit(db, "authentication.failed", "FAILURE", reason="local_sign_in_failed",
                  request_id=request.state.request_id)
            raise HTTPException(status_code=401, detail="Invalid email or password")
        try:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT c.password_hash,u.status FROM local_credentials c JOIN users u ON u.id=c.user_id "
                "WHERE c.user_id=?", (row["user_id"],),
            ).fetchone()
            if not current or current["status"] != "ACTIVE" or current["password_hash"] != row["password_hash"]:
                db.rollback()
                raise HTTPException(status_code=401, detail="Invalid email or password")
            cookie = create_session(db, row["user_id"], request.app.state.settings)
            db.execute("UPDATE users SET last_login_at=? WHERE id=?", (utc_iso(), row["user_id"]))
            audit(db, "authentication.succeeded", "SUCCESS", actor=row["user_id"], target=row["user_id"],
                  reason="local_password", request_id=request.state.request_id)
            db.commit()
        except (sqlite3.Error, ValueError):
            db.rollback()
            raise
        response.headers.append("set-cookie", cookie_header(
            cookie, request.app.state.settings, max_age=request.app.state.settings.session_max_age,
        ))
        return {"password_change_required": bool(row["must_change_password"])}
    finally:
        db.close()


@router.post("/change-password", status_code=204)
def change_password(
    body: PasswordBody, request: Request,
    session: AuthenticatedSession = Depends(active_session),
    _csrf: None = Depends(require_csrf),
):
    db = connect(request.app.state.db_path)
    try:
        _limit(db, request, "change-password")
        row = db.execute("SELECT password_hash FROM local_credentials WHERE user_id=?", (session.user_id,)).fetchone()
        if not row or not verify_password(row["password_hash"], body.current_password):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        if hmac.compare_digest(body.current_password.encode("utf-8"), body.new_password.encode("utf-8")):
            raise HTTPException(status_code=422, detail="Choose a different password")
        try:
            password_hash = hash_password(body.new_password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        db.execute("BEGIN IMMEDIATE")
        try:
            changed = db.execute(
                "UPDATE local_credentials SET password_hash=?,must_change_password=0 "
                "WHERE user_id=? AND password_hash=?", (password_hash, session.user_id, row["password_hash"]),
            )
            if changed.rowcount != 1:
                db.rollback()
                raise HTTPException(status_code=409, detail="Password changed concurrently; sign in again")
            db.execute("UPDATE sessions SET revoked_at=?,revoked_by=?,revocation_reason='password_changed' "
                       "WHERE user_id=? AND id!=? AND revoked_at IS NULL",
                       (utc_iso(), session.user_id, session.user_id, session.session_id))
            audit(db, "password.changed", "SUCCESS", actor=session.user_id, target=session.user_id,
                  request_id=request.state.request_id)
            db.commit()
        except sqlite3.Error:
            db.rollback()
            raise
        return Response(status_code=204)
    finally:
        db.close()
