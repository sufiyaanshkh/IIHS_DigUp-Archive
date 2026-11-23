from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.auth.sessions import audit, utc_iso

_hasher = PasswordHasher()
_dummy_hash = _hasher.hash("not-a-real-user-password")
_email_pattern = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{1,63}$")


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not _email_pattern.fullmatch(email):
        raise ValueError("Enter a valid email address")
    return email


def validate_name(value: str) -> str:
    name = value.strip()
    if not 2 <= len(name) <= 120:
        raise ValueError("Name must contain 2 to 120 characters")
    return name


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128 or len(password.encode("utf-8")) > 512:
        raise ValueError("Password must contain 12 to 128 characters")
    groups = (
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() for character in password),
    )
    if sum(groups) < 3 or len(set(password)) < 8:
        raise ValueError("Password must contain at least 8 distinct characters and 3 of: lowercase, uppercase, number, symbol")
    return _hasher.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    if len(password.encode("utf-8")) > 512:
        return False
    try:
        return _hasher.verify(encoded or _dummy_hash, password) and encoded is not None
    except VerifyMismatchError:
        return False


def create_local_user(
    db: sqlite3.Connection, *, email: str, display_name: str, password_hash: str,
    role: str, must_change_password: bool, actor: str | None, request_id: str | None,
) -> str:
    email = normalize_email(email)
    name = validate_name(display_name)
    user_id = str(uuid.uuid4())
    now = utc_iso()
    db.execute(
        "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
        "VALUES(?,NULL,NULL,?,?,?,'ACTIVE',?,?)",
        (user_id, email, name, role, now, now),
    )
    db.execute(
        "INSERT INTO local_credentials(user_id,email_normalized,password_hash,must_change_password) "
        "VALUES(?,?,?,?)", (user_id, email, password_hash, int(must_change_password)),
    )
    audit(db, "user.created", "SUCCESS", actor=actor, target=user_id,
          after=f'{{"role":"{role}","status":"ACTIVE"}}', request_id=request_id)
    return user_id


def check_rate_limit(db: sqlite3.Connection, category: str, client: str) -> bool:
    key = hashlib.sha256(f"{category}:{client}".encode()).hexdigest()
    now = int(time.time())
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DELETE FROM local_auth_attempts WHERE window_start < ?", (now - 900,))
        row = db.execute("SELECT attempts,window_start FROM local_auth_attempts WHERE key=?", (key,)).fetchone()
        if row and row["window_start"] > now - 900:
            attempts = row["attempts"] + 1
            db.execute("UPDATE local_auth_attempts SET attempts=? WHERE key=?", (attempts, key))
        else:
            attempts = 1
            db.execute("INSERT OR REPLACE INTO local_auth_attempts(key,attempts,window_start) VALUES(?,?,?)",
                       (key, attempts, now))
        db.commit()
        return attempts <= 20
    except sqlite3.Error:
        db.rollback()
        raise
