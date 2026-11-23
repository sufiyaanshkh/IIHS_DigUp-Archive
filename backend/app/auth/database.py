"""Initialize and migrate the separate IIHS Media Archive authentication database.

Run from ``backend/`` with ``python -m app.auth.database migrate``. The database
defaults to ``../var/auth.sqlite`` and can be relocated with IIHS_AUTH_DB_PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "var" / "auth.sqlite"
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """A migration failed or a previously applied migration was changed."""


def database_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve an explicit path, configured path, or project-local development default."""
    configured = path if path is not None else os.environ.get("IIHS_AUTH_DB_PATH")
    if configured is None:
        return DEFAULT_DB_PATH
    resolved = Path(configured).expanduser()
    return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open the auth database with foreign keys enabled on this connection."""
    db_path = database_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        _chmod_database(db_path)
    except OSError:
        connection.close()
        raise
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _chmod_database(path: Path) -> None:
    """Restrict the database file to its owner where POSIX permissions are available."""
    try:
        path.chmod(0o600)
    except (NotImplementedError, OSError):
        if os.name == "posix":
            raise


def _migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    invalid = [file.name for file in files if not MIGRATION_NAME.fullmatch(file.name)]
    if invalid:
        raise MigrationError(f"invalid migration filename(s): {', '.join(invalid)}")
    return files


def _execute_migration(connection: sqlite3.Connection, sql: str) -> None:
    """Execute a multi-statement migration, including trigger bodies, in the open txn."""
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise MigrationError("migration ends with an incomplete SQL statement")


def migrate(path: str | os.PathLike[str] | None = None) -> Path:
    """Apply each unapplied SQL migration atomically and retain existing data."""
    db_path = database_path(path)
    files = _migration_files()
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.commit()

        for migration in files:
            sql = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            rebuild_users = migration.name == "003_local_auth.sql"
            if rebuild_users:
                connection.execute("PRAGMA foreign_keys = OFF")
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Recheck while holding the write lock so two initializers cannot both
                # decide that the same migration is pending.
                applied = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = ?",
                    (migration.name,),
                ).fetchone()
                if applied is not None:
                    if applied["checksum"] != checksum:
                        raise MigrationError(
                            f"applied migration {migration.name} was modified; add a new migration"
                        )
                    connection.rollback()
                    continue

                if rebuild_users:
                    extensions = connection.execute(
                        "SELECT name FROM sqlite_master WHERE tbl_name='users' AND sql IS NOT NULL "
                        "AND (type='trigger' OR (type='index' AND name != 'idx_users_role_status'))"
                    ).fetchall()
                    if extensions:
                        raise MigrationError("local auth migration found custom user indexes or triggers; review required")
                _execute_migration(connection, sql)
                if rebuild_users and connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise MigrationError("local auth migration would violate foreign keys")
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                    (migration.name, checksum,
                     datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                connection.commit()
            except (sqlite3.Error, MigrationError) as exc:
                if connection.in_transaction:
                    connection.rollback()
                if isinstance(exc, MigrationError):
                    raise
                raise MigrationError(f"failed applying {migration.name}: {exc}") from exc
            finally:
                if rebuild_users:
                    connection.execute("PRAGMA foreign_keys = ON")

        _chmod_database(db_path)
        return db_path
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "migrate"),
                        help="initialize the database or apply pending migrations")
    parser.add_argument("--db", help="database path (overrides IIHS_AUTH_DB_PATH)")
    args = parser.parse_args()
    try:
        path = migrate(args.db)
    except (MigrationError, OSError, sqlite3.Error) as exc:
        print(f"auth database {args.command} failed: {exc}", file=sys.stderr)
        return 1
    print(f"authentication database ready: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
