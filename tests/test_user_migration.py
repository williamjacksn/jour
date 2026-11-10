import contextlib
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

import fort

import jour.models


class MoveJournalsToAdminTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.data_dir = pathlib.Path(tmp.name)
        self.enterContext(mock.patch("jour.models.paths.DATA_DIR", self.data_dir))
        self.db = fort.SQLiteDatabase(str(self.data_dir / "jour.db"))
        self.addCleanup(self.db.cnx.close)

    def make_legacy_fts_table(self) -> None:
        self.db.u("""
            create virtual table journal_entries
            using fts5(journal_id unindexed, journal_date, journal_data)
        """)

    def make_v2_database(self, admin_email: str | None) -> None:
        """Build a database the way it looked before multi-user support."""
        self.db.u("""
            create table settings (
                setting_id text primary key, setting_value text
            )
        """)
        self.db.u("""
            create table journals (
                journal_id uuid primary key,
                journal_date date,
                journal_data blob
            )
        """)
        self.make_legacy_fts_table()
        entries = [
            {"i": "id-1", "d": "2026-11-09", "t": "first entry"},
            {"i": "id-2", "d": "2026-11-10", "t": "second entry"},
        ]
        self.db.b("insert into journal_entries values (:i, :d, :t)", entries)
        if admin_email:
            sql = "insert into settings values ('admin/email', :e)"
            self.db.u(sql, {"e": admin_email})
        self.db.u("pragma user_version = 2")

    def tables(self) -> set[str]:
        sql = "select name from sqlite_master where type = 'table'"
        return {r["name"] for r in self.db.q(sql)}

    def open_user_db(self, email: str) -> fort.SQLiteDatabase:
        user = jour.models.users.get_by_email(self.db, email)
        if user is None:
            self.fail(f"No user for {email}")
        user_db = jour.models.userdb.open_db(user["user_id"])
        self.addCleanup(user_db.cnx.close)
        return user_db

    def test_entries_move_to_admin_user_database(self) -> None:
        self.make_v2_database("Admin@Example.test")

        jour.models.init(self.db)

        self.assertEqual(
            jour.models.get_schema_version(self.db), len(jour.models.MIGRATIONS)
        )
        user_db = self.open_user_db("admin@example.test")
        rows = user_db.q("""
            select journal_id, journal_date, journal_data
            from journal_entries
            order by journal_date
        """)
        self.assertEqual(
            [(r["journal_id"], r["journal_date"], r["journal_data"]) for r in rows],
            [
                ("id-1", "2026-11-09", "first entry"),
                ("id-2", "2026-11-10", "second entry"),
            ],
        )
        self.assertEqual(len(jour.models.journals.search(user_db, "second")), 1)

    def test_legacy_tables_removed_after_backup(self) -> None:
        self.make_v2_database("admin@example.test")

        jour.models.init(self.db)

        self.assertNotIn("journal_entries", self.tables())
        self.assertNotIn("journals", self.tables())
        backup = self.data_dir / "jour.db.pre-multiuser.bak"
        self.assertTrue(backup.exists())
        with contextlib.closing(sqlite3.connect(backup)) as old:
            count = old.execute("select count(*) from journal_entries").fetchone()[0]
        self.assertEqual(count, 2)

    def test_missing_admin_email_aborts_without_losing_anything(self) -> None:
        self.make_v2_database(None)

        with self.assertRaisesRegex(RuntimeError, "admin_email"):
            jour.models.init(self.db)

        self.assertEqual(jour.models.get_schema_version(self.db), 3)
        self.assertEqual(self.db.q_val("select count(*) from journal_entries"), 2)

    def test_retry_after_interrupted_copy_does_not_duplicate(self) -> None:
        self.make_v2_database("admin@example.test")
        jour.models.init(self.db)
        # Simulate a crash after copying but before the legacy table was dropped
        self.make_legacy_fts_table()
        self.db.u("insert into journal_entries values ('id-1', '2026-11-09', 'first')")
        self.db.u("pragma user_version = 3")

        jour.models.init(self.db)

        user_db = self.open_user_db("admin@example.test")
        self.assertEqual(user_db.q_val("select count(*) from journal_entries"), 2)
        self.assertNotIn("journal_entries", self.tables())

    def test_database_without_entries_migrates_without_admin_email(self) -> None:
        jour.models.init(self.db)

        self.assertEqual(
            jour.models.get_schema_version(self.db), len(jour.models.MIGRATIONS)
        )
        self.assertNotIn("journals", self.tables())
        self.assertEqual(self.db.q("select * from users"), [])


class UserDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.enterContext(
            mock.patch("jour.models.paths.DATA_DIR", pathlib.Path(tmp.name))
        )

    def test_user_database_is_created_with_schema(self) -> None:
        db = jour.models.userdb.open_db("6f1c1d3e-8a55-4c64-9a0f-5d7d3b1c2e10")
        self.addCleanup(db.cnx.close)

        self.assertEqual(
            jour.models.schema.get_version(db), len(jour.models.userdb.MIGRATIONS)
        )
        self.assertEqual(db.q_val("select count(*) from journal_entries"), 0)

    def test_user_id_cannot_escape_data_directory(self) -> None:
        with self.assertRaises(ValueError):
            jour.models.userdb.open_db("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
