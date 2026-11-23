from __future__ import annotations

import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from app.auth.database import MIGRATIONS_DIR, MigrationError, migrate


class AuthDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.db_path = Path(self.temp_dir.name) / "auth.sqlite"
        migrate(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add_user(self, connection: sqlite3.Connection, *, user_id: str = "user-1",
                 tenant: str = "tenant-1", oid: str = "oid-1", role: str = "EMPLOYEE",
                 status: str = "ACTIVE", email: str = "person@example.org") -> None:
        connection.execute(
            "INSERT INTO users (id, entra_tenant_id, entra_object_id, email, display_name, "
            "role, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, tenant, oid, email, "Person", role, status,
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )

    def test_initialization_creates_required_tables_and_indexes(self) -> None:
        with self.connect() as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"schema_migrations", "users", "sessions", "audit_events"} <= tables)
            indexes = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertTrue({"idx_users_role_status", "idx_sessions_user",
                             "idx_sessions_expiry_revocation", "idx_audit_timestamp",
                             "idx_audit_actor", "idx_audit_target"} <= indexes)

    def test_initialization_is_idempotent_and_preserves_existing_data(self) -> None:
        with self.connect() as connection:
            self.add_user(connection)
            before = connection.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        migrate(self.db_path)
        with self.connect() as connection:
            self.assertEqual(connection.execute("SELECT id FROM users").fetchone()[0], "user-1")
            self.assertEqual(connection.execute("SELECT version, checksum FROM schema_migrations").fetchall(), before)

    def test_migration_tracking_records_initial_schema_once(self) -> None:
        migrate(self.db_path)
        with self.connect() as connection:
            rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
        self.assertEqual([row[0] for row in rows], [
            "001_initial_auth_schema.sql", "002_oidc_flow_sessions.sql", "003_local_auth.sql"
        ])

    def test_failed_migration_rolls_back_its_schema_changes(self) -> None:
        migrations = Path(self.temp_dir.name) / "migrations"
        migrations.mkdir()
        (migrations / "001_failure_probe.sql").write_text(
            "CREATE TABLE rollback_probe (id TEXT PRIMARY KEY);\n"
            "CREATE TABLE invalid_probe (id TEXT NOT NULL, id TEXT NOT NULL);\n",
            encoding="utf-8",
        )
        with patch("app.auth.database.MIGRATIONS_DIR", migrations):
            with self.assertRaisesRegex(MigrationError, "failed applying 001_failure_probe.sql"):
                migrate(self.db_path)
        with self.connect() as connection:
            found = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rollback_probe'"
            ).fetchone()
        self.assertIsNone(found)

    def test_local_auth_migration_preserves_existing_users_sessions_and_audit(self) -> None:
        db_path = Path(self.temp_dir.name) / "upgrade.sqlite"
        old_migrations = Path(self.temp_dir.name) / "old-migrations"
        old_migrations.mkdir()
        for name in ("001_initial_auth_schema.sql", "002_oidc_flow_sessions.sql"):
            shutil.copyfile(MIGRATIONS_DIR / name, old_migrations / name)
        with patch("app.auth.database.MIGRATIONS_DIR", old_migrations):
            migrate(db_path)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            self.add_user(db, role="SUPER_ADMIN")
            db.execute("INSERT INTO sessions(id,user_id,session_secret_hash,created_at,last_seen_at,expires_at) "
                       "VALUES('s','user-1','hash','t','t','future')")
            db.execute("INSERT INTO audit_events(id,actor_user_id,target_user_id,action,timestamp,outcome) "
                       "VALUES('a','user-1','user-1','existing','t','SUCCESS')")
        migrate(db_path)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("PRAGMA foreign_keys=ON")
            self.assertEqual(db.execute("SELECT id,role,entra_tenant_id FROM users").fetchone(),
                             ("user-1", "SUPER_ADMIN", "tenant-1"))
            self.assertEqual(db.execute("SELECT user_id FROM sessions").fetchone(), ("user-1",))
            self.assertEqual(db.execute("SELECT actor_user_id,target_user_id FROM audit_events").fetchone(),
                             ("user-1", "user-1"))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("SELECT bootstrap_completed FROM auth_configuration").fetchone(), (1,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE users SET role='EMPLOYEE' WHERE id='user-1'")

    def test_local_auth_migration_rolls_back_if_existing_foreign_keys_are_invalid(self) -> None:
        db_path = Path(self.temp_dir.name) / "invalid-upgrade.sqlite"
        old_migrations = Path(self.temp_dir.name) / "old-migrations"
        old_migrations.mkdir()
        for name in ("001_initial_auth_schema.sql", "002_oidc_flow_sessions.sql"):
            shutil.copyfile(MIGRATIONS_DIR / name, old_migrations / name)
        with patch("app.auth.database.MIGRATIONS_DIR", old_migrations):
            migrate(db_path)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("INSERT INTO sessions(id,user_id,session_secret_hash,created_at,last_seen_at,expires_at) "
                       "VALUES('s','missing','hash','t','t','future')")
        with self.assertRaisesRegex(MigrationError, "violate foreign keys"):
            migrate(db_path)
        with closing(sqlite3.connect(db_path)) as db, db:
            columns = {row[1]: row for row in db.execute("PRAGMA table_info(users)")}
            self.assertEqual(columns["entra_tenant_id"][3], 1)
            self.assertIsNone(db.execute("SELECT 1 FROM schema_migrations WHERE version='003_local_auth.sql'").fetchone())
            self.assertEqual(db.execute("SELECT user_id FROM sessions").fetchone(), ("missing",))

    def test_local_auth_migration_refuses_custom_user_schema_objects(self) -> None:
        db_path = Path(self.temp_dir.name) / "custom-upgrade.sqlite"
        old_migrations = Path(self.temp_dir.name) / "old-migrations"
        old_migrations.mkdir()
        for name in ("001_initial_auth_schema.sql", "002_oidc_flow_sessions.sql"):
            shutil.copyfile(MIGRATIONS_DIR / name, old_migrations / name)
        with patch("app.auth.database.MIGRATIONS_DIR", old_migrations):
            migrate(db_path)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("CREATE INDEX custom_user_email ON users(email)")
        with self.assertRaisesRegex(MigrationError, "custom user indexes or triggers"):
            migrate(db_path)
        with closing(sqlite3.connect(db_path)) as db, db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='custom_user_email'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM schema_migrations WHERE version='003_local_auth.sql'").fetchone())

    def test_all_role_values_are_accepted(self) -> None:
        roles = ("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR", "REVIEWER", "EMPLOYEE")
        with self.connect() as connection:
            for number, role in enumerate(roles):
                self.add_user(connection, user_id=f"user-{number}", oid=f"oid-{number}", role=role)

    def test_invalid_role_is_rejected(self) -> None:
        with self.connect() as connection, self.assertRaises(sqlite3.IntegrityError):
            self.add_user(connection, role="OWNER")

    def test_all_account_status_values_are_accepted(self) -> None:
        statuses = ("ACTIVE", "SUSPENDED", "DEACTIVATED", "LOCKED")
        with self.connect() as connection:
            for number, status in enumerate(statuses):
                self.add_user(connection, user_id=f"user-{number}", oid=f"oid-{number}", status=status)

    def test_invalid_account_status_is_rejected(self) -> None:
        with self.connect() as connection, self.assertRaises(sqlite3.IntegrityError):
            self.add_user(connection, status="PENDING")

    def test_entra_identity_is_unique_but_email_is_not_the_identity_key(self) -> None:
        with self.connect() as connection:
            self.add_user(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                self.add_user(connection, user_id="user-2", email="other@example.org")

    def test_session_requires_existing_user_and_is_unique_by_hash(self) -> None:
        with self.connect() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("s0", "missing", "hash0", "t", "t", "t", None, None, None),
                )
            self.add_user(connection)
            values = ("s1", "user-1", "hash1", "t", "t", "t", None, None, None)
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("s2", "user-1", "hash1", "t", "t", "t", None, None, None),
                )

    def test_audit_event_user_references_are_enforced_and_history_is_append_only(self) -> None:
        with self.connect() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO audit_events (id, actor_user_id, action, timestamp, outcome) "
                    "VALUES ('a0', 'missing', 'role.change', 't', 'SUCCESS')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO audit_events (id, target_user_id, action, timestamp, outcome) "
                    "VALUES ('a2', 'missing', 'role.change', 't', 'SUCCESS')")
            self.add_user(connection)
            connection.execute(
                "INSERT INTO audit_events (id, actor_user_id, target_user_id, action, timestamp, outcome) "
                "VALUES ('a1', 'user-1', 'user-1', 'role.change', 't', 'SUCCESS')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM audit_events WHERE id='a1'")

    def test_data_persists_after_reopening_database(self) -> None:
        with self.connect() as connection:
            self.add_user(connection)
        with self.connect() as reopened:
            self.assertEqual(reopened.execute("SELECT email FROM users WHERE id='user-1'").fetchone()[0],
                             "person@example.org")


if __name__ == "__main__":
    unittest.main()
