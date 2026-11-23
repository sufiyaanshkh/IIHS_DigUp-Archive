from __future__ import annotations

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.authorization import AuthenticatedSession, require_csrf, require_roles
from app.auth.database import connect
from app.auth.local import create_local_user, hash_password, normalize_email, validate_name
from app.auth.sessions import audit, utc_iso

router = APIRouter(prefix="/api/admin", tags=["administration"])
Role = Literal["SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR", "REVIEWER", "EMPLOYEE"]


class CreateUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=2, max_length=120)
    role: Role
    temporary_password: str = Field(max_length=128)


class UpdateUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    role: Role | None = None
    status: Literal["ACTIVE", "SUSPENDED", "DEACTIVATED", "LOCKED"] | None = None


class RegistrationSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class TemporaryPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_password: str = Field(max_length=128)


def _permitted(actor: AuthenticatedSession, role: str) -> bool:
    return actor.role == "SUPER_ADMIN" or role in ("EMPLOYEE", "ARCHIVE_OPERATOR")


def _check_actor(db: sqlite3.Connection, actor: AuthenticatedSession) -> None:
    row = db.execute(
        "SELECT u.role,u.status,s.revoked_at,s.expires_at,COALESCE(c.must_change_password,0) AS must_change "
        "FROM sessions s JOIN users u ON u.id=s.user_id "
        "LEFT JOIN local_credentials c ON c.user_id=u.id WHERE s.id=? AND u.id=?",
        (actor.session_id, actor.user_id),
    ).fetchone()
    if (not row or row["status"] != "ACTIVE" or row["revoked_at"] or row["expires_at"] <= utc_iso()
            or row["must_change"] or row["role"] != actor.role):
        raise HTTPException(status_code=403, detail="Your authorization has changed; sign in again")


@router.get("/users")
def users(request: Request, actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN"))):
    db = connect(request.app.state.db_path)
    try:
        rows = db.execute(
            "SELECT u.id,u.display_name,u.email,u.role,u.status, "
            "CASE WHEN c.user_id IS NULL THEN 'entra' ELSE 'local' END AS identity "
            "FROM users u LEFT JOIN local_credentials c ON c.user_id=u.id "
            "ORDER BY u.display_name COLLATE NOCASE,u.id"
        ).fetchall()
        return {"users": [dict(row) for row in rows if _permitted(actor, row["role"])]}
    finally:
        db.close()


@router.post("/users", status_code=201)
def create_user(
    body: CreateUser, request: Request,
    actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN")),
    _csrf: None = Depends(require_csrf),
):
    if not _permitted(actor, body.role):
        raise HTTPException(status_code=403, detail="You cannot assign this role")
    try:
        encoded = hash_password(body.temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db = connect(request.app.state.db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            _check_actor(db, actor)
            user_id = create_local_user(db, email=body.email, display_name=body.display_name,
                                        password_hash=encoded, role=body.role, must_change_password=True,
                                        actor=actor.user_id, request_id=request.state.request_id)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Account could not be created") from exc
        return {"id": user_id}
    finally:
        db.close()


@router.patch("/users/{user_id}")
def update_user(
    user_id: str, body: UpdateUser, request: Request,
    actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN")),
    _csrf: None = Depends(require_csrf),
):
    if not body.model_fields_set:
        raise HTTPException(status_code=422, detail="No changes supplied")
    db = connect(request.app.state.db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            _check_actor(db, actor)
            row = db.execute(
                "SELECT u.id,u.display_name,u.email,u.role,u.status,c.user_id AS local_user_id "
                "FROM users u LEFT JOIN local_credentials c ON c.user_id=u.id WHERE u.id=?", (user_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            role = body.role if body.role is not None else row["role"]
            status = body.status if body.status is not None else row["status"]
            if not _permitted(actor, row["role"]) or not _permitted(actor, role):
                raise HTTPException(status_code=403, detail="You cannot modify this account or assign this role")
            if body.email is not None and not row["local_user_id"]:
                raise HTTPException(status_code=422, detail="Entra controls this account's email")
            name = validate_name(body.display_name) if body.display_name is not None else row["display_name"]
            email = normalize_email(body.email) if body.email is not None else row["email"]
            now = utc_iso()
            db.execute("UPDATE users SET display_name=?,email=?,role=?,status=?,updated_at=?,"
                       "deactivated_at=?,deactivated_by=? WHERE id=?",
                       (name, email, role, status, now,
                        now if status == "DEACTIVATED" else None,
                        actor.user_id if status == "DEACTIVATED" else None, user_id))
            if body.email is not None:
                db.execute("UPDATE local_credentials SET email_normalized=? WHERE user_id=?", (email, user_id))
            if role != row["role"] or status != row["status"] or email != row["email"]:
                db.execute("UPDATE sessions SET revoked_at=?,revoked_by=?,revocation_reason='account_changed' "
                           "WHERE user_id=? AND revoked_at IS NULL", (now, actor.user_id, user_id))
            audit(db, "user.updated", "SUCCESS", actor=actor.user_id, target=user_id,
                  before=json.dumps({"role": row["role"], "status": row["status"]}),
                  after=json.dumps({"role": role, "status": status}), request_id=request.state.request_id)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            db.rollback()
            detail = "The last active Super Administrator must be retained" if "last active Super" in str(exc) else "Account could not be updated"
            raise HTTPException(status_code=409, detail=detail) from exc
        return {"id": user_id}
    finally:
        db.close()


@router.get("/audit")
def audit_log(request: Request, limit: int = Query(default=100, ge=1, le=200),
              _actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN"))):
    db = connect(request.app.state.db_path)
    try:
        rows = db.execute(
            "SELECT id,actor_user_id,target_user_id,action,timestamp,before_value,after_value,reason,request_id,outcome "
            "FROM audit_events ORDER BY timestamp DESC, rowid DESC LIMIT ?", (limit,),
        ).fetchall()
        return {"events": [dict(row) for row in rows]}
    finally:
        db.close()


@router.post("/users/{user_id}/temporary-password")
def reset_password(
    user_id: str, body: TemporaryPassword, request: Request,
    actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN")),
    _csrf: None = Depends(require_csrf),
):
    try:
        encoded = hash_password(body.temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db = connect(request.app.state.db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            _check_actor(db, actor)
            row = db.execute(
                "SELECT u.role,c.user_id AS local_user_id FROM users u "
                "LEFT JOIN local_credentials c ON c.user_id=u.id WHERE u.id=?", (user_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            if not _permitted(actor, row["role"]):
                raise HTTPException(status_code=403, detail="You cannot modify this account")
            if not row["local_user_id"]:
                raise HTTPException(status_code=422, detail="Entra controls this account's password")
            db.execute("UPDATE local_credentials SET password_hash=?,must_change_password=1 WHERE user_id=?",
                       (encoded, user_id))
            db.execute("UPDATE sessions SET revoked_at=?,revoked_by=?,revocation_reason='password_reset' "
                       "WHERE user_id=? AND revoked_at IS NULL", (utc_iso(), actor.user_id, user_id))
            audit(db, "password.reset", "SUCCESS", actor=actor.user_id, target=user_id,
                  request_id=request.state.request_id)
            db.commit()
        except (HTTPException, sqlite3.Error):
            db.rollback()
            raise
        return {"message": "Temporary password set"}
    finally:
        db.close()


@router.get("/registration")
def registration_configuration(request: Request,
                               _actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN"))):
    db = connect(request.app.state.db_path)
    try:
        enabled = bool(db.execute("SELECT registration_enabled FROM auth_configuration WHERE id=1").fetchone()[0])
        allowed = request.app.state.settings.demo_registration_allowed
        return {"enabled": enabled, "deployment_allowed": allowed, "effective": enabled and allowed}
    finally:
        db.close()


@router.put("/registration")
def set_registration(body: RegistrationSetting, request: Request,
                     actor: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN")),
                     _csrf: None = Depends(require_csrf)):
    if body.enabled and not request.app.state.settings.demo_registration_allowed:
        raise HTTPException(status_code=403, detail="Demo registration is not allowed by the deployment")
    db = connect(request.app.state.db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            _check_actor(db, actor)
            before = bool(db.execute("SELECT registration_enabled FROM auth_configuration WHERE id=1").fetchone()[0])
            db.execute("UPDATE auth_configuration SET registration_enabled=? WHERE id=1", (int(body.enabled),))
            audit(db, "registration.changed", "SUCCESS", actor=actor.user_id,
                  before=json.dumps({"enabled": before}), after=json.dumps({"enabled": body.enabled}),
                  request_id=request.state.request_id)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except sqlite3.Error:
            db.rollback()
            raise
        return {"enabled": body.enabled}
    finally:
        db.close()
