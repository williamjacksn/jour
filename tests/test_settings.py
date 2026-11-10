import pathlib
import tempfile
import unittest

import fort

import jour.models
import jour.models.settings


class SettingsRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.db = fort.SQLiteDatabase(str(pathlib.Path(tmp.name) / "test.db"))
        jour.models.init(self.db)
        self.settings = jour.models.settings.Settings(self.db)

    def test_properties_match_registry(self) -> None:
        for name in jour.models.settings.REGISTRY:
            value = f"value-for-{name}"
            self.settings.set_by_name(name, value)
            self.assertEqual(getattr(self.settings, name), value)

    def test_encrypted_values_not_stored_in_plaintext(self) -> None:
        self.settings.set_by_name("openid_client_secret", "hunter2")
        raw = self.settings.get_str("openid/client-secret")
        self.assertNotIn("hunter2", raw)
        self.assertEqual(self.settings.openid_client_secret, "hunter2")


class SchemaVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.db = fort.SQLiteDatabase(str(pathlib.Path(tmp.name) / "test.db"))

    def test_fresh_db_gets_latest_version(self) -> None:
        self.assertEqual(jour.models.get_schema_version(self.db), 0)
        jour.models.init(self.db)
        self.assertEqual(
            jour.models.get_schema_version(self.db), len(jour.models.MIGRATIONS)
        )

    def test_init_is_idempotent(self) -> None:
        jour.models.init(self.db)
        jour.models.init(self.db)
        self.assertEqual(
            jour.models.get_schema_version(self.db), len(jour.models.MIGRATIONS)
        )

    def test_unversioned_existing_db_is_adopted(self) -> None:
        self.db.u(
            "create table settings (setting_id text primary key, setting_value text)"
        )
        self.db.u("insert into settings values ('user/email', 'a@example.test')")
        jour.models.init(self.db)
        self.assertEqual(
            jour.models.settings.Settings(self.db).admin_email, "a@example.test"
        )
        self.assertEqual(
            jour.models.get_schema_version(self.db), len(jour.models.MIGRATIONS)
        )

    def test_newer_db_is_rejected(self) -> None:
        self.db.u("pragma user_version = 999")
        with self.assertRaises(RuntimeError):
            jour.models.init(self.db)
