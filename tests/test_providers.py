import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

import fort

import cli
import jour.models
from tests import support

MS_DISCOVERY = (
    "https://login.microsoftonline.com/consumers/v2.0/.well-known/openid-configuration"
)


class LegacyConfigMigrationTests(unittest.TestCase):
    """Migration 6 turns the old single-provider settings into a provider row."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.enterContext(
            mock.patch("jour.models.paths.DATA_DIR", pathlib.Path(tmp.name))
        )
        self.db = fort.SQLiteDatabase(str(pathlib.Path(tmp.name) / "jour.db"))
        self.addCleanup(self.db.cnx.close)
        # A database exactly as it was before providers existed
        jour.models.schema.migrate(self.db, jour.models.MIGRATIONS[:5])
        self.settings = jour.models.settings.Settings(self.db)

    def set_legacy(self, discovery: str, secret: str = "old-secret") -> None:  # noqa: S107
        self.settings.set_str("openid/client-id", "old-client")
        self.settings.set_str("openid/discovery-document", discovery)
        if secret:
            self.settings.set_enc("openid/client-secret", secret)

    def test_microsoft_config_becomes_the_microsoft_provider(self) -> None:
        self.set_legacy(MS_DISCOVERY)

        jour.models.init(self.db)

        provider = jour.models.providers.get(self.db, "microsoft")
        if provider is None:
            self.fail("provider was not created")
        self.assertEqual(provider["display_name"], "Microsoft")
        self.assertEqual(provider["client_id"], "old-client")
        self.assertEqual(provider["discovery_document"], MS_DISCOVERY)
        self.assertTrue(provider["is_enabled"])
        self.assertTrue(provider["trust_email"])
        self.assertEqual(
            jour.models.providers.client_secret(self.settings, provider), "old-secret"
        )
        self.assertEqual(self.settings.legacy_provider, "microsoft")

    def test_old_settings_are_removed(self) -> None:
        self.set_legacy(MS_DISCOVERY)

        jour.models.init(self.db)

        remaining = self.settings.keys()
        self.assertFalse({k for k in remaining if k.startswith("openid/")})

    def test_other_identity_providers_get_a_generic_id(self) -> None:
        self.set_legacy("https://auth.example.test/.well-known/openid-configuration")

        jour.models.init(self.db)

        self.assertIsNotNone(jour.models.providers.get(self.db, "oidc"))
        self.assertEqual(self.settings.legacy_provider, "oidc")

    def test_no_legacy_config_means_no_provider(self) -> None:
        jour.models.init(self.db)

        self.assertEqual(jour.models.providers.list_all(self.db), [])
        self.assertEqual(self.settings.legacy_provider, "")

    def test_existing_user_links_on_first_sign_in_through_the_provider(self) -> None:
        self.set_legacy(MS_DISCOVERY)
        jour.models.init(self.db)
        user = jour.models.users.get_or_create(self.db, "alice@example.test")
        provider = jour.models.providers.get(self.db, "microsoft")
        if provider is None:
            self.fail("provider was not created")

        resolved, failure = jour.models.signin.resolve_user(
            self.db,
            self.settings,
            provider,
            {"sub": "ms-sub", "email": "alice@example.test"},
        )

        self.assertIsNone(failure)
        if resolved is None:
            self.fail("user should have been resolved")
        self.assertEqual(resolved["user_id"], user["user_id"])
        self.assertEqual(
            jour.models.identities.find_user_id(self.db, "microsoft", "ms-sub"),
            user["user_id"],
        )

    def test_rerunning_the_migration_is_harmless(self) -> None:
        self.set_legacy(MS_DISCOVERY)
        jour.models.init(self.db)
        self.db.u("pragma user_version = 5")

        jour.models.init(self.db)

        self.assertEqual(len(jour.models.providers.list_all(self.db)), 1)
        self.assertEqual(self.settings.legacy_provider, "microsoft")


class ProviderModelTests(support.AppTestCase):
    def test_validate_accepts_good_input(self) -> None:
        errors = jour.models.providers.validate(
            "google",
            display_name="Google",
            discovery_document="https://accounts.google.com/.well-known/x",
            client_id="abc",
            has_secret=True,
        )

        self.assertEqual(errors, [])

    def test_validate_rejects_bad_ids(self) -> None:
        for bad in ("", "New", "new", "1abc", "a b", "a/b", "x" * 40, "../etc"):
            with self.subTest(provider_id=bad):
                errors = jour.models.providers.validate(
                    bad,
                    display_name="n",
                    discovery_document="https://x.test/d",
                    client_id="c",
                    has_secret=True,
                )
                self.assertTrue(errors)

    def test_save_keeps_the_secret_when_none_is_given(self) -> None:
        before = jour.models.providers.get(self.database, "idp")
        if before is None:
            self.fail("provider missing")

        jour.models.providers.save(
            self.database,
            self.settings,
            "idp",
            display_name="New name",
            discovery_document=before["discovery_document"],
            client_id=before["client_id"],
            secret=None,
            is_enabled=True,
            trust_email=True,
        )

        after = jour.models.providers.get(self.database, "idp")
        if after is None:
            self.fail("provider missing")
        self.assertEqual(after["client_secret"], before["client_secret"])
        self.assertEqual(after["display_name"], "New name")

    def test_secret_is_encrypted_at_rest(self) -> None:
        provider = jour.models.providers.get(self.database, "idp")
        if provider is None:
            self.fail("provider missing")

        self.assertNotIn("provider-secret", provider["client_secret"])
        self.assertEqual(
            jour.models.providers.client_secret(self.settings, provider),
            "provider-secret",
        )


class CliTests(support.AppTestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with (
            mock.patch("sys.argv", ["cli.py", *argv]),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            try:
                cli.main()
            except SystemExit as e:
                code = int(e.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_preset_fills_in_defaults(self) -> None:
        code, out, _ = self.run_cli(
            "provider",
            "set",
            "google",
            "--client-id",
            "gid",
            "--client-secret",
            "gsecret",
        )

        self.assertEqual(code, 0)
        self.assertIn("Saved provider google", out)
        provider = jour.models.providers.get(self.database, "google")
        if provider is None:
            self.fail("provider was not created")
        self.assertEqual(provider["display_name"], "Google")
        self.assertIn("accounts.google.com", provider["discovery_document"])
        self.assertTrue(provider["trust_email"])
        self.assertTrue(provider["is_enabled"])

    def test_missing_pieces_are_reported_and_nothing_is_saved(self) -> None:
        code, _, err = self.run_cli("provider", "set", "custom")

        self.assertEqual(code, 1)
        self.assertIn("Client secret is required", err)
        self.assertIsNone(jour.models.providers.get(self.database, "custom"))

    def test_update_changes_only_what_is_given(self) -> None:
        code, _, _ = self.run_cli("provider", "set", "idp", "--no-enabled")

        self.assertEqual(code, 0)
        provider = jour.models.providers.get(self.database, "idp")
        if provider is None:
            self.fail("provider missing")
        self.assertFalse(provider["is_enabled"])
        self.assertEqual(provider["client_id"], support.CLIENT_ID)
        self.assertTrue(provider["trust_email"])

    def test_list_never_prints_the_secret(self) -> None:
        code, out, _ = self.run_cli("provider", "list")

        self.assertEqual(code, 0)
        self.assertIn("idp:", out)
        self.assertIn("client_secret: (set)", out)
        self.assertNotIn("provider-secret", out)

    def test_remove_is_refused_while_users_sign_in_with_it(self) -> None:
        jour.models.identities.link(self.database, "idp", "sub", "user")

        code, _, err = self.run_cli("provider", "remove", "idp")

        self.assertEqual(code, 1)
        self.assertIn("disable it instead", err)
        self.assertIsNotNone(jour.models.providers.get(self.database, "idp"))

    def test_remove_deletes_an_unused_provider(self) -> None:
        code, out, _ = self.run_cli("provider", "remove", "idp")

        self.assertEqual(code, 0)
        self.assertIn("Removed provider idp", out)
        self.assertIsNone(jour.models.providers.get(self.database, "idp"))


if __name__ == "__main__":
    unittest.main()
