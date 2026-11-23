from __future__ import annotations

import argparse
import getpass
import sqlite3

from app.auth.database import connect, migrate
from app.auth.local import create_local_user, hash_password
from app.auth.sessions import audit


def bootstrap(db_path: str, email: str, name: str, password: str) -> str:
    password_hash = hash_password(password)
    db = connect(db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        completed = db.execute("SELECT bootstrap_completed FROM auth_configuration WHERE id=1").fetchone()[0]
        if completed or db.execute("SELECT 1 FROM users WHERE role='SUPER_ADMIN' LIMIT 1").fetchone():
            raise ValueError("Super Administrator bootstrap has already been completed")
        user_id = create_local_user(db, email=email, display_name=name, password_hash=password_hash,
                                    role="SUPER_ADMIN", must_change_password=False, actor=None, request_id=None)
        db.execute("UPDATE auth_configuration SET bootstrap_completed=1 WHERE id=1")
        audit(db, "bootstrap.super_admin_created", "SUCCESS", target=user_id,
              after='{"role":"SUPER_ADMIN","status":"ACTIVE"}', reason="one_time_local_cli_bootstrap")
        db.commit()
        return user_id
    except (sqlite3.Error, ValueError):
        if db.in_transaction:
            db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the initial local Super Administrator")
    parser.add_argument("--db", required=True, help="Explicit authentication database path")
    args = parser.parse_args()
    try:
        migrate(args.db)
        name = input("Display name: ")
        email = input("Email address: ")
        password = getpass.getpass("Password (not displayed): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise ValueError("Passwords do not match")
        bootstrap(args.db, email, name, password)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(f"Bootstrap failed: {exc}")
        return 1
    print("Initial Super Administrator created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
