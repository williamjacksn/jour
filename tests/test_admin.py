import pathlib
import secrets
import tempfile
import unittest
from unittest import mock

import lxml.html

import jour.app
import jour.models

ADMIN = "owner@example.test"


class AdminTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.data_dir = pathlib.Path(tmp.name)
        self.enterContext(mock.patch("jour.models.paths.DATA_DIR", self.data_dir))
        self.enterContext(
            mock.patch.dict(
                jour.app.app.config, TESTING=True, SECRET_KEY=secrets.token_hex(32)
            )
        )
        self.database = jour.app._get_db()
        self.addCleanup(self.database.cnx.close)
        jour.models.init(self.database)
        self.settings = jour.models.settings.Settings(self.database)
        self.settings.admin_email = ADMIN
        self.settings.openid_client_id = "client-id"
        self.settings.openid_client_secret = "super-secret-value"  # noqa: S105
        self.settings.openid_discovery_document = "https://idp.example.test/.well-known"
        self.settings.scheme = "https"
        self.client = jour.app.app.test_client()

    def sign_in_as(self, email: str) -> None:
        with self.client.session_transaction() as session:
            session["email"] = email

    def make_user(self, email: str) -> dict:
        """Create a user with a journal entry, as if they had signed in."""
        user = jour.models.users.get_or_create(self.database, email)
        user_db = jour.models.userdb.open_db(user["user_id"])
        user_db.u("insert into journal_entries values ('1', '2026-11-10', 'hello')")
        user_db.cnx.close()
        return user

    def user_db_path(self, user: dict) -> pathlib.Path:
        return jour.models.paths.user_db_path(user["user_id"])

    def text(self, path: str) -> str:
        return self.client.get(path).get_data(as_text=True)


class AccessTests(AdminTestCase):
    def test_non_admin_is_forbidden_everywhere(self) -> None:
        other = self.make_user("other@example.test")
        self.sign_in_as("other@example.test")
        uid = other["user_id"]

        for method, path in [
            ("GET", "/admin"),
            ("GET", "/admin/users"),
            ("GET", "/admin/settings"),
            ("POST", "/admin/settings"),
            ("POST", f"/admin/users/{uid}/disable"),
            ("POST", f"/admin/users/{uid}/enable"),
            ("POST", f"/admin/users/{uid}/delete"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.client.open(path, method=method).status_code, 403)

        self.assertIsNotNone(jour.models.users.get_by_id(self.database, uid))
        self.assertTrue(self.user_db_path(other).exists())

    def test_signed_out_gets_landing_not_admin(self) -> None:
        response = self.client.get("/admin/users")

        document = lxml.html.fromstring(response.data)
        self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])

    def test_admin_check_ignores_email_case(self) -> None:
        self.sign_in_as("Owner@Example.TEST")

        self.assertEqual(self.client.get("/admin/users").status_code, 200)

    def test_only_admin_sees_admin_menu_link(self) -> None:
        self.sign_in_as("other@example.test")
        self.settings.signup_policy = "open"
        links = lxml.html.fromstring(self.text("/2026/11")).xpath(
            "//a[@href='/admin/users']"
        )
        self.assertEqual(links, [])

        self.sign_in_as(ADMIN)
        links = lxml.html.fromstring(self.text("/2026/11")).xpath(
            "//a[@href='/admin/users']"
        )
        self.assertEqual(len(links), 1)


class SignupPolicyTests(AdminTestCase):
    def assert_denied(self, email: str) -> None:
        self.sign_in_as(email)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Not invited", response.get_data(as_text=True))
        self.assertIsNone(jour.models.users.get_by_email(self.database, email))

    def assert_allowed(self, email: str) -> None:
        self.sign_in_as(email)
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertIsNotNone(jour.models.users.get_by_email(self.database, email))

    def test_unset_policy_fails_closed(self) -> None:
        self.assert_denied("stranger@example.test")
        self.assertFalse((self.data_dir / "users").exists())

    def test_admin_may_always_sign_up(self) -> None:
        self.assert_allowed(ADMIN)

    def test_allowlist_matches_emails_and_domains(self) -> None:
        self.settings.signup_policy = "allowlist"
        self.settings.signup_allowlist = "friend@example.test\n@family.test, "

        self.assert_allowed("Friend@Example.test")
        self.assert_allowed("anyone@family.test")
        self.assert_denied("stranger@example.test")
        self.assert_denied("x@sub.family.test")

    def test_open_policy_allows_anyone(self) -> None:
        self.settings.signup_policy = "open"

        self.assert_allowed("stranger@example.test")

    def test_unknown_policy_value_fails_closed(self) -> None:
        self.settings.signup_policy = "yolo"

        self.assert_denied("stranger@example.test")

    def test_existing_users_are_unaffected_by_stricter_policy(self) -> None:
        self.make_user("old@example.test")
        self.settings.signup_policy = "allowlist"

        self.assert_allowed("old@example.test")


class UserManagementTests(AdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other = self.make_user("other@example.test")
        self.uid = self.other["user_id"]
        self.sign_in_as(ADMIN)

    def test_user_list_shows_users_and_entry_counts(self) -> None:
        document = lxml.html.fromstring(self.text("/admin/users"))

        rows = {
            tr.xpath("string(td[1]/text()[1])"): tr.xpath("string(td[4])")
            for tr in document.xpath("//tbody/tr")
        }
        # Viewing the page created the admin's own (empty) account too
        self.assertEqual(rows, {"other@example.test": "1", ADMIN: "0"})

    def test_admin_row_is_listed_with_badge_and_no_actions(self) -> None:
        jour.models.users.get_or_create(self.database, ADMIN)

        document = lxml.html.fromstring(self.text("/admin/users"))

        row = document.xpath(f"//tr[td[contains(., '{ADMIN}')]]")[0]
        self.assertIn("admin", row.xpath("string(td[1])"))
        self.assertEqual(row.xpath(".//form"), [])

    def test_disable_blocks_user_and_enable_restores(self) -> None:
        self.client.post(f"/admin/users/{self.uid}/disable")

        self.sign_in_as("other@example.test")
        response = self.client.get("/2026/11")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Account disabled", response.get_data(as_text=True))
        self.assertTrue(self.user_db_path(self.other).exists())

        self.sign_in_as(ADMIN)
        self.client.post(f"/admin/users/{self.uid}/enable")
        self.sign_in_as("other@example.test")
        self.assertEqual(self.client.get("/2026/11").status_code, 200)

    def test_delete_removes_user_and_database_file(self) -> None:
        path = self.user_db_path(self.other)
        self.assertTrue(path.exists())

        response = self.client.post(f"/admin/users/{self.uid}/delete")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(jour.models.users.get_by_id(self.database, self.uid))
        self.assertFalse(path.exists())

    def test_admin_cannot_disable_or_delete_themselves(self) -> None:
        admin = jour.models.users.get_or_create(self.database, ADMIN)
        path = self.user_db_path(admin)
        jour.models.userdb.open_db(admin["user_id"]).cnx.close()

        for action in ("disable", "delete"):
            with self.subTest(action=action):
                response = self.client.post(f"/admin/users/{admin['user_id']}/{action}")
                self.assertEqual(response.status_code, 400)

        self.assertTrue(path.exists())
        self.assertEqual(self.client.get("/2026/11").status_code, 200)

    def test_unknown_user_is_404(self) -> None:
        response = self.client.post("/admin/users/not-a-user/delete")

        self.assertEqual(response.status_code, 404)

    def test_get_does_not_change_users(self) -> None:
        self.assertEqual(
            self.client.get(f"/admin/users/{self.uid}/delete").status_code, 405
        )


class SettingsPageTests(AdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sign_in_as(ADMIN)

    def valid_form(self, **overrides: str) -> dict[str, str]:
        form = {
            "admin_email": ADMIN,
            "openid_client_id": "client-id",
            "openid_client_secret": "",
            "openid_discovery_document": "https://idp.example.test/.well-known",
            "scheme": "https",
            "signup_policy": "allowlist",
            "signup_allowlist": "",
        }
        form.update(overrides)
        return form

    def test_page_never_shows_client_secret(self) -> None:
        html = self.client.get("/admin/settings").get_data(as_text=True)

        self.assertNotIn("super-secret-value", html)
        self.assertIn("A secret is set", html)
        self.assertIn("client-id", html)

    def test_save_updates_settings_and_keeps_secret_when_blank(self) -> None:
        form = self.valid_form(
            openid_client_id="new-id",
            signup_policy="open",
            signup_allowlist="B@x.test\n@Corp.test, a@x.test",
        )

        response = self.client.post("/admin/settings", data=form)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.settings.openid_client_id, "new-id")
        self.assertEqual(self.settings.signup_policy, "open")
        self.assertEqual(
            self.settings.signup_allowlist, "@corp.test\na@x.test\nb@x.test"
        )
        self.assertEqual(self.settings.openid_client_secret, "super-secret-value")

    def test_save_replaces_secret_when_given(self) -> None:
        self.client.post(
            "/admin/settings",
            data=self.valid_form(openid_client_secret="fresh"),  # noqa: S106
        )

        self.assertEqual(self.settings.openid_client_secret, "fresh")

    def test_invalid_input_is_rejected_and_nothing_is_saved(self) -> None:
        form = self.valid_form(
            admin_email="not-an-email",
            openid_client_id="changed",
            openid_discovery_document="javascript:alert(1)",
            scheme="ftp",
            signup_policy="yolo",
        )

        response = self.client.post("/admin/settings", data=form)

        self.assertEqual(response.status_code, 400)
        text = response.get_data(as_text=True)
        for message in (
            "Admin email must be an email address.",
            "Discovery document must be an http or https URL.",
            "Redirect URI scheme must be http or https.",
            "Choose who can create an account.",
        ):
            self.assertIn(message, text)
        self.assertEqual(self.settings.openid_client_id, "client-id")
        self.assertEqual(self.settings.admin_email, ADMIN)

    def test_secret_is_not_written_to_debug_log(self) -> None:
        with self.assertLogs("jour.app", level="DEBUG") as logs:
            self.client.post(
                "/admin/settings",
                data=self.valid_form(openid_client_secret="leaky-secret-123"),  # noqa: S106
            )

        self.assertNotIn("leaky-secret-123", "\n".join(logs.output))
        self.assertEqual(self.settings.openid_client_secret, "leaky-secret-123")


class SignInTrackingTests(AdminTestCase):
    def test_sign_in_updates_last_sign_in(self) -> None:
        user = self.make_user("other@example.test")
        self.database.u("update users set last_sign_in_at = null")
        self.settings.scheme = "http"
        with (
            mock.patch("jour.app.httpx.get") as http_get,
            mock.patch("jour.app.httpx.post") as http_post,
            mock.patch("jour.oidc.verify_id_token") as verify,
        ):
            http_get.return_value.json.return_value = {"token_endpoint": "https://t"}
            http_post.return_value.is_error = False
            http_post.return_value.json.return_value = {"id_token": "x"}
            verify.return_value = {
                "email": "Other@Example.test",
                "email_verified": True,
            }
            with self.client.session_transaction() as session:
                session["state"] = "abc"

            self.client.get("/authorize?state=abc&code=xyz")

        updated = jour.models.users.get_by_id(self.database, user["user_id"])
        if updated is None:
            self.fail("user vanished")
        self.assertIsNotNone(updated["last_sign_in_at"])


if __name__ == "__main__":
    unittest.main()
