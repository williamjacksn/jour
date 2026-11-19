import pathlib

import lxml.html

import jour.models
from tests import support
from tests.support import ADMIN


class AdminTestCase(support.AppTestCase):
    def user_db_path(self, user: dict) -> pathlib.Path:
        return jour.models.paths.user_db_path(user["user_id"])


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
            ("GET", "/admin/providers"),
            ("GET", "/admin/providers/new"),
            ("POST", "/admin/providers/new"),
            ("GET", "/admin/providers/idp"),
            ("POST", "/admin/providers/idp"),
            ("POST", "/admin/providers/idp/delete"),
            ("POST", f"/admin/users/{uid}/disable"),
            ("POST", f"/admin/users/{uid}/enable"),
            ("POST", f"/admin/users/{uid}/delete"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.client.open(path, method=method).status_code, 403)

        self.assertIsNotNone(jour.models.users.get_by_id(self.database, uid))
        self.assertTrue(self.user_db_path(other).exists())
        self.assertIsNotNone(jour.models.providers.get(self.database, "idp"))

    def test_signed_out_gets_landing_not_admin(self) -> None:
        response = self.client.get("/admin/users")

        document = lxml.html.fromstring(response.data)
        self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])

    def test_admin_check_ignores_email_case(self) -> None:
        self.sign_in_as("Owner@Example.TEST")

        self.assertEqual(self.client.get("/admin/users").status_code, 200)

    def test_only_admin_sees_admin_menu_link(self) -> None:
        self.sign_in_as("other@example.test")
        links = lxml.html.fromstring(self.page("/2026/11")).xpath(
            "//a[@href='/admin/users']"
        )
        self.assertEqual(links, [])

        self.sign_in_as(ADMIN)
        links = lxml.html.fromstring(self.page("/2026/11")).xpath(
            "//a[@href='/admin/users']"
        )
        self.assertEqual(len(links), 1)


class UserManagementTests(AdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other = self.make_user("other@example.test")
        self.uid = self.other["user_id"]
        self.sign_in_as(ADMIN)

    def test_user_list_shows_users_and_entry_counts(self) -> None:
        document = lxml.html.fromstring(self.page("/admin/users"))

        rows = {
            tr.xpath("string(td[1]/text()[1])"): tr.xpath("string(td[4])")
            for tr in document.xpath("//tbody/tr")
        }
        # The admin's own (empty) account exists because they are signed in
        self.assertEqual(rows, {"other@example.test": "1", ADMIN: "0"})

    def test_admin_row_has_badge_and_no_actions(self) -> None:
        document = lxml.html.fromstring(self.page("/admin/users"))

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

    def test_delete_removes_user_identities_and_database_file(self) -> None:
        jour.models.identities.link(self.database, "idp", "sub-1", self.uid)
        path = self.user_db_path(self.other)
        self.assertTrue(path.exists())

        response = self.client.post(f"/admin/users/{self.uid}/delete")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(jour.models.users.get_by_id(self.database, self.uid))
        self.assertIsNone(
            jour.models.identities.find_user_id(self.database, "idp", "sub-1")
        )
        self.assertFalse(path.exists())

    def test_deleted_user_is_signed_out_not_recreated(self) -> None:
        self.client.post(f"/admin/users/{self.uid}/delete")
        # The deleted user still has a cookie naming their old id
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = self.uid

        document = lxml.html.fromstring(self.page("/2026/11"))

        self.assertIsNone(
            jour.models.users.get_by_email(self.database, "other@example.test")
        )
        self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])

    def test_admin_cannot_disable_or_delete_themselves(self) -> None:
        admin = jour.models.users.get_by_email(self.database, ADMIN)
        if admin is None:
            self.fail("admin account should exist")
        jour.models.userdb.open_db(admin["user_id"]).cnx.close()
        path = self.user_db_path(admin)

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
            "scheme": "https",
            "signup_policy": "allowlist",
            "signup_allowlist": "",
        }
        form.update(overrides)
        return form

    def test_page_has_no_identity_provider_fields(self) -> None:
        document = lxml.html.fromstring(self.page("/admin/settings"))

        names = set(document.xpath("//form//*[@name]/@name"))
        self.assertEqual(
            names, {"admin_email", "scheme", "signup_policy", "signup_allowlist"}
        )

    def test_save_updates_settings(self) -> None:
        form = self.valid_form(
            scheme="http",
            signup_policy="open",
            signup_allowlist="B@x.test\n@Corp.test, a@x.test",
        )

        response = self.client.post("/admin/settings", data=form)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.settings.scheme, "http")
        self.assertEqual(self.settings.signup_policy, "open")
        self.assertEqual(
            self.settings.signup_allowlist, "@corp.test\na@x.test\nb@x.test"
        )

    def test_invalid_input_is_rejected_and_nothing_is_saved(self) -> None:
        form = self.valid_form(
            admin_email="not-an-email", scheme="ftp", signup_policy="yolo"
        )

        response = self.client.post("/admin/settings", data=form)

        self.assertEqual(response.status_code, 400)
        text = response.get_data(as_text=True)
        for message in (
            "Admin email must be an email address.",
            "Redirect URI scheme must be http or https.",
            "Choose who can create an account.",
        ):
            self.assertIn(message, text)
        self.assertEqual(self.settings.scheme, "https")
        self.assertEqual(self.settings.admin_email, ADMIN)


class ProviderAdminTests(AdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sign_in_as(ADMIN)

    def valid_form(self, **overrides: str) -> dict[str, str]:
        form = {
            "provider_id": "google",
            "display_name": "Google",
            "discovery_document": "https://accounts.google.com/.well-known/openid-configuration",
            "client_id": "google-client",
            "client_secret": "google-secret",
            "is_enabled": "on",
            "trust_email": "on",
        }
        form.update(overrides)
        return form

    def test_list_shows_providers_with_callback_urls_and_offers_presets(self) -> None:
        self.add_provider("other")
        jour.models.identities.link(self.database, "idp", "s", "some-user")

        document = lxml.html.fromstring(self.page("/admin/providers"))

        rows = {
            tr.xpath("string(td[1]/div)"): (
                tr.xpath("string(td[4])"),
                tr.xpath("string(td[5])"),
            )
            for tr in document.xpath("//tbody/tr")
        }
        self.assertEqual(
            rows,
            {
                "idp": ("1", "https://localhost/authorize/idp"),
                "other": ("0", "https://localhost/authorize/other"),
            },
        )
        offered = document.xpath("//a[contains(@href, 'preset=')]/@href")
        self.assertEqual(
            sorted(offered),
            [
                "/admin/providers/new?preset=google",
                "/admin/providers/new?preset=microsoft",
            ],
        )

    def test_legacy_provider_shows_its_original_callback_url(self) -> None:
        self.settings.legacy_provider = "idp"

        document = lxml.html.fromstring(self.page("/admin/providers"))

        self.assertEqual(
            document.xpath("string(//tbody/tr/td[5])"), "https://localhost/authorize"
        )

    def test_preset_prefills_the_new_provider_form(self) -> None:
        document = lxml.html.fromstring(self.page("/admin/providers/new?preset=google"))

        def value(name: str) -> str:
            return document.xpath(f"string(//input[@name='{name}']/@value)")

        self.assertEqual(value("provider_id"), "google")
        self.assertEqual(value("display_name"), "Google")
        self.assertIn("accounts.google.com", value("discovery_document"))
        self.assertTrue(document.xpath("//input[@name='trust_email' and @checked]"))
        self.assertIn("https://localhost/authorize/google", document.text_content())

    def test_create_stores_provider_with_encrypted_secret(self) -> None:
        response = self.client.post("/admin/providers/new", data=self.valid_form())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"], "/admin/providers/google?saved=1"
        )
        provider = jour.models.providers.get(self.database, "google")
        if provider is None:
            self.fail("provider was not created")
        self.assertEqual(provider["client_id"], "google-client")
        self.assertTrue(provider["is_enabled"])
        self.assertTrue(provider["trust_email"])
        self.assertNotIn("google-secret", provider["client_secret"])
        self.assertEqual(
            jour.models.providers.client_secret(self.settings, provider),
            "google-secret",
        )

    def test_edit_page_never_shows_the_secret(self) -> None:
        provider = jour.models.providers.get(self.database, "idp")
        if provider is None:
            self.fail("provider missing")

        html = self.page("/admin/providers/idp")

        self.assertNotIn("provider-secret", html)
        # The stored ciphertext must not be sent back to the browser either
        self.assertNotIn(provider["client_secret"], html)
        self.assertIn("A secret is set", html)
        document = lxml.html.fromstring(html)
        self.assertEqual(document.xpath("//input[@name='client_secret']/@value"), [""])

    def test_secret_typed_into_a_rejected_form_is_not_echoed_back(self) -> None:
        form = self.valid_form(
            provider_id="idp",
            client_id="",
            client_secret="typed-secret",  # noqa: S106
        )

        response = self.client.post("/admin/providers/idp", data=form)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("typed-secret", response.get_data(as_text=True))

    def test_edit_keeps_secret_when_blank_and_replaces_when_given(self) -> None:
        self.client.post(
            "/admin/providers/idp",
            data=self.valid_form(
                provider_id="idp", display_name="Renamed", client_secret=""
            ),
        )
        provider = jour.models.providers.get(self.database, "idp")
        if provider is None:
            self.fail("provider vanished")
        self.assertEqual(provider["display_name"], "Renamed")
        self.assertEqual(
            jour.models.providers.client_secret(self.settings, provider),
            "provider-secret",
        )

        self.client.post(
            "/admin/providers/idp",
            data=self.valid_form(provider_id="idp", client_secret="rotated"),  # noqa: S106
        )
        provider = jour.models.providers.get(self.database, "idp")
        if provider is None:
            self.fail("provider vanished")
        self.assertEqual(
            jour.models.providers.client_secret(self.settings, provider), "rotated"
        )

    def test_unchecked_boxes_disable_and_untrust(self) -> None:
        form = self.valid_form(provider_id="idp")
        del form["is_enabled"]
        del form["trust_email"]

        self.client.post("/admin/providers/idp", data=form)

        provider = jour.models.providers.get(self.database, "idp")
        if provider is None:
            self.fail("provider vanished")
        self.assertFalse(provider["is_enabled"])
        self.assertFalse(provider["trust_email"])

    def test_invalid_input_is_rejected(self) -> None:
        form = self.valid_form(
            provider_id="Bad ID!",
            display_name="",
            discovery_document="javascript:alert(1)",
            client_id="",
            client_secret="",
        )

        response = self.client.post("/admin/providers/new", data=form)

        self.assertEqual(response.status_code, 400)
        text = response.get_data(as_text=True)
        for message in (
            "ID must be lowercase letters",
            "Name is required.",
            "Discovery document must be an http or https URL.",
            "Client ID is required.",
            "Client secret is required.",
        ):
            self.assertIn(message, text)
        self.assertIsNone(jour.models.providers.get(self.database, "bad id!"))

    def test_cannot_create_a_duplicate_or_reserved_id(self) -> None:
        duplicate = self.client.post(
            "/admin/providers/new", data=self.valid_form(provider_id="idp")
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already exists", duplicate.get_data(as_text=True))

        reserved = self.client.post(
            "/admin/providers/new", data=self.valid_form(provider_id="new")
        )
        self.assertEqual(reserved.status_code, 400)

    def test_cannot_submit_the_form_without_a_secret_for_a_new_provider(self) -> None:
        response = self.client.post(
            "/admin/providers/new", data=self.valid_form(client_secret="")
        )

        self.assertEqual(response.status_code, 400)

    def test_unknown_provider_is_404(self) -> None:
        self.assertEqual(self.client.get("/admin/providers/nope").status_code, 404)
        self.assertEqual(
            self.client.post("/admin/providers/nope/delete").status_code, 404
        )

    def test_delete_removes_an_unused_provider(self) -> None:
        response = self.client.post("/admin/providers/idp/delete")

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(jour.models.providers.get(self.database, "idp"))

    def test_delete_is_refused_while_users_sign_in_with_it(self) -> None:
        jour.models.identities.link(self.database, "idp", "sub-1", "some-user")

        response = self.client.post("/admin/providers/idp/delete")

        self.assertEqual(response.status_code, 409)
        self.assertIsNotNone(jour.models.providers.get(self.database, "idp"))
