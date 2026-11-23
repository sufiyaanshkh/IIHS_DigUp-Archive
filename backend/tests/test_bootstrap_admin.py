from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from argparse import Namespace
from unittest.mock import patch

from app.auth.bootstrap_admin import bootstrap, run
from app.auth.database import migrate


class BootstrapAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.db_path = Path(self.tmp.name) / "auth.sqlite"
        migrate(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bootstrap_creates_super_admin_and_audit_event(self) -> None:
        user_id = bootstrap(str(self.db_path), "tenant", "oid", "Member", "member@iihs.ac.in")
        with closing(sqlite3.connect(self.db_path)) as db, db:
            row = db.execute("SELECT role,status FROM users WHERE id=?", (user_id,)).fetchone()
            self.assertEqual(row, ("SUPER_ADMIN", "ACTIVE"))
            audit = db.execute("SELECT action,outcome,target_user_id FROM audit_events").fetchone()
            self.assertEqual(audit, ("bootstrap.super_admin_created", "SUCCESS", user_id))

    def test_bootstrap_refuses_when_any_super_admin_exists(self) -> None:
        bootstrap(str(self.db_path), "tenant", "oid", "First", "first@iihs.ac.in")
        with self.assertRaisesRegex(ValueError, "already exists"):
            bootstrap(str(self.db_path), "tenant", "oid2", "Second", "second@iihs.ac.in")

    def test_existing_active_employee_is_promoted_transactionally(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) VALUES('u','tenant','oid','old@iihs.ac.in','Old','EMPLOYEE','ACTIVE','t','t')")
        user_id = bootstrap(str(self.db_path), "tenant", "oid", "Member", "member@iihs.ac.in")
        with closing(sqlite3.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()[0], "SUPER_ADMIN")

    def test_cli_refuses_tenant_mismatch_before_graph_lookup(self) -> None:
        args = Namespace(tenant_id="different", object_id="object", db=str(self.db_path))
        with patch.dict("os.environ", {"IIHS_ENTRA_TENANT_ID": "configured"}), \
                patch("app.auth.bootstrap_admin.resolve_member") as resolve:
            result = __import__("asyncio").run(run(args))
        self.assertEqual(result, 1)
        resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
