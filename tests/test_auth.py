import datetime as dt
import urllib.parse

import lxml.html

import jour.models
from tests import support
from tests.support import ADMIN, OTHER_KEY


class SignedOutTests(support.AppTestCase):
    def test_signed_out_requests_show_landing_without_starting_oauth(self) -> None:
        routes = [
            ("GET", "/"),
            ("GET", "/2026/11"),
            ("GET", "/2026/11/10"),
            ("GET", "/2026/11/10/edit"),
            ("POST", "/2026/11/10/update"),
            ("POST", "/2026/11/10/delete"),
            ("POST", "/search"),
        ]
        for method, path in routes:
            with self.subTest(method=method, path=path):
                response = self.client.open(path, method=method)

                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Location", response.headers)
                document = lxml.html.fromstring(response.data)
                self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])
                self.assertEqual(
                    document.xpath("//main//a[@href='/sign-in']/text()"), ["Sign in"]
                )

        self.http_get.assert_not_called()
        self.assertFalse((self.data_dir / "users").exists())
        self.assertEqual(self.database.q("select * from users"), [])
        with self.client.session_transaction() as session:
            self.assertNotIn("state", session)

    def test_signed_in_user_goes_to_current_month(self) -> None:
        self.sign_in_as("alice@example.test")

        response = self.client.get("/")

        today = dt.datetime.now(tz=dt.UTC).astimezone().date()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], today.strftime("/%Y/%m"))
        self.http_get.assert_not_called()

    def test_session_for_a_deleted_user_is_signed_out(self) -> None:
        user = self.sign_in_as("alice@example.test")
        jour.models.users.delete(self.database, user["user_id"])

        document = lxml.html.fromstring(self.page("/"))

        self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])


class SignInPageTests(support.AppTestCase):
    def test_single_provider_goes_straight_to_it(self) -> None:
        response = self.client.get("/sign-in")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/sign-in/idp")

    def test_several_providers_show_a_chooser(self) -> None:
        self.add_provider("other", display_name="Other ID")

        response = self.client.get("/sign-in")

        document = lxml.html.fromstring(response.data)
        links = {
            a.get("href"): a.text_content() for a in document.xpath("//main//a[@class]")
        }
        self.assertEqual(
            links,
            {
                "/sign-in/idp": "Continue with Idp",
                "/sign-in/other": "Continue with Other ID",
            },
        )

    def test_disabled_providers_are_hidden(self) -> None:
        self.add_provider("off", enabled=False)

        response = self.client.get("/sign-in")

        self.assertEqual(response.headers["Location"], "/sign-in/idp")
        self.assertEqual(self.client.get("/sign-in/off").status_code, 404)

    def test_no_providers_says_so(self) -> None:
        self.database.u("delete from providers")

        response = self.client.get("/sign-in")

        self.assertEqual(response.status_code, 503)
        self.assertIn("Sign-in unavailable", response.get_data(as_text=True))

    def test_unknown_provider_is_404(self) -> None:
        self.assertEqual(self.client.get("/sign-in/nope").status_code, 404)

    def test_sign_in_sends_the_user_to_the_provider(self) -> None:
        response = self.client.get("/sign-in/idp")

        self.assertEqual(response.status_code, 307)
        location = urllib.parse.urlparse(response.headers["Location"])
        self.assertEqual(location.netloc, "idp.example.test")
        self.assertEqual(location.path, "/authorize")
        query = urllib.parse.parse_qs(location.query)
        self.assertEqual(query["client_id"], [support.CLIENT_ID])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["openid email profile"])
        self.assertEqual(query["redirect_uri"], ["https://localhost/authorize/idp"])
        with self.client.session_transaction() as session:
            self.assertEqual(query["state"], [session["state"]])
            self.assertEqual(query["nonce"], [session["nonce"]])
            self.assertNotEqual(session["nonce"], session["state"])
            self.assertEqual(session["provider"], "idp")

    def test_legacy_provider_keeps_its_original_callback_url(self) -> None:
        self.settings.legacy_provider = "idp"

        response = self.client.get("/sign-in/idp")

        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(response.headers["Location"]).query
        )
        self.assertEqual(query["redirect_uri"], ["https://localhost/authorize"])


class CallbackTests(support.AppTestCase):
    def assert_refused(self, response: object, status: int) -> None:
        self.assertEqual(getattr(response, "status_code", None), status)
        self.assertIsNone(self.session_user_id())
        self.assertEqual(self.database.q("select * from users"), [])
        self.assertEqual(self.database.q("select * from identities"), [])

    def test_sign_in_creates_user_identity_and_session(self) -> None:
        response = self.callback(
            {"email": "Alice@Example.test", "email_verified": True}
        )

        self.assertEqual(response.status_code, 302)
        user = jour.models.users.get_by_email(self.database, "alice@example.test")
        if user is None:
            self.fail("user was not created")
        self.assertEqual(self.session_user_id(), user["user_id"])
        self.assertEqual(
            jour.models.identities.find_user_id(
                self.database, "idp", "sub-Alice@Example.test"
            ),
            user["user_id"],
        )
        self.assertIsNotNone(user["last_sign_in_at"])
        with self.client.session_transaction() as session:
            self.assertNotIn("state", session)
            self.assertNotIn("nonce", session)
            self.assertNotIn("provider", session)

    def test_returning_user_gets_the_same_account(self) -> None:
        first = self.callback({"email": "alice@example.test", "email_verified": True})
        user_id = self.session_user_id()
        self.client.post("/sign-out")

        second = self.callback({"email": "alice@example.test", "email_verified": True})

        self.assertEqual((first.status_code, second.status_code), (302, 302))
        self.assertEqual(self.session_user_id(), user_id)
        self.assertEqual(self.database.q_val("select count(*) from users"), 1)

    def test_account_follows_the_subject_when_email_changes(self) -> None:
        self.callback({"email": "old@example.test", "sub": "stable"})
        user_id = self.session_user_id()
        self.client.post("/sign-out")

        self.callback({"email": "new@example.test", "sub": "stable"})

        self.assertEqual(self.session_user_id(), user_id)
        self.assertEqual(self.database.q_val("select count(*) from users"), 1)

    def test_string_email_verified_from_providers_like_apple(self) -> None:
        ok = self.callback({"email": "a@example.test", "email_verified": "true"})
        self.assertEqual(ok.status_code, 302)
        self.client.post("/sign-out")

        refused = self.callback({"email": "b@example.test", "email_verified": "false"})

        self.assertEqual(refused.status_code, 403)

    def test_unverified_email_is_refused(self) -> None:
        response = self.callback({"email": "a@example.test", "email_verified": False})

        self.assert_refused(response, 403)

    def test_missing_email_is_refused(self) -> None:
        self.assert_refused(self.callback({"name": "No Email"}), 403)

    def test_missing_subject_is_rejected(self) -> None:
        response = self.callback({"email": "a@example.test", "sub": ""})

        self.assert_refused(response, 403)

    def test_untrusted_provider_must_assert_verified_email(self) -> None:
        self.add_provider("shaky", trust_email=False)

        absent = self.callback({"email": "a@example.test"}, provider_id="shaky")
        self.assertEqual(absent.status_code, 403)
        self.assertEqual(self.database.q("select * from users"), [])

        asserted = self.callback(
            {"email": "a@example.test", "email_verified": True}, provider_id="shaky"
        )
        self.assertEqual(asserted.status_code, 302)

    def test_trusted_provider_may_omit_the_verified_claim(self) -> None:
        # Microsoft personal accounts never send email_verified
        self.assertEqual(self.callback({"email": "a@example.test"}).status_code, 302)

    def test_second_provider_links_to_existing_account_by_email(self) -> None:
        self.add_provider("second")
        self.callback({"email": "alice@example.test", "email_verified": True})
        user_id = self.session_user_id()
        if user_id is None:
            self.fail("first sign-in should have created a session")
        self.client.post("/sign-out")

        self.callback(
            {"email": "alice@example.test", "email_verified": True},
            provider_id="second",
        )

        self.assertEqual(self.session_user_id(), user_id)
        self.assertEqual(self.database.q_val("select count(*) from users"), 1)
        self.assertEqual(
            jour.models.identities.providers_for_user(self.database, user_id),
            ["idp", "second"],
        )

    def test_untrusted_provider_cannot_claim_an_existing_email(self) -> None:
        existing = self.make_user("alice@example.test")
        self.add_provider("shaky", trust_email=False)

        response = self.callback(
            {"email": "alice@example.test", "email_verified": True},
            provider_id="shaky",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("already exists", response.get_data(as_text=True))
        self.assertIsNone(self.session_user_id())
        self.assertEqual(self.database.q("select * from identities"), [])
        self.assertEqual(
            jour.models.users.get_by_id(self.database, existing["user_id"]), existing
        )

    def test_untrusted_provider_cannot_claim_the_admin_email(self) -> None:
        self.settings.signup_policy = "allowlist"
        self.add_provider("shaky", trust_email=False)

        response = self.callback({"email": ADMIN}, provider_id="shaky")

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.session_user_id())

    def test_signup_policy_applies_to_new_accounts_from_any_provider(self) -> None:
        self.settings.signup_policy = "allowlist"

        response = self.callback({"email": "stranger@example.test"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("Not invited", response.get_data(as_text=True))
        self.assertIsNone(self.session_user_id())
        self.assertEqual(self.database.q("select * from users"), [])
        self.assertFalse((self.data_dir / "users").exists())

    def test_admin_may_always_sign_up(self) -> None:
        self.settings.signup_policy = "allowlist"

        self.assertEqual(self.callback({"email": ADMIN}).status_code, 302)

    def test_existing_users_are_unaffected_by_a_stricter_policy(self) -> None:
        self.callback({"email": "old@example.test"})
        self.client.post("/sign-out")
        self.settings.signup_policy = "allowlist"

        self.assertEqual(self.callback({"email": "old@example.test"}).status_code, 302)

    def test_token_signed_by_unknown_key_is_rejected(self) -> None:
        response = self.callback({"email": "a@example.test"}, key=OTHER_KEY)

        self.assert_refused(response, 401)

    def test_wrong_audience_is_rejected(self) -> None:
        response = self.callback({"email": "a@example.test", "aud": "another-app"})

        self.assert_refused(response, 401)

    def test_wrong_nonce_is_rejected(self) -> None:
        response = self.callback({"email": "a@example.test", "nonce": "attacker"})

        self.assert_refused(response, 401)

    def test_missing_nonce_in_session_is_rejected(self) -> None:
        response = self.callback({"email": "a@example.test"}, nonce_in_session=None)

        self.assert_refused(response, 401)

    def test_state_mismatch_is_rejected(self) -> None:
        response = self.callback({"email": "a@example.test"}, state_in_request="x")

        self.assert_refused(response, 401)

    def test_callback_for_a_different_provider_than_started_is_rejected(self) -> None:
        self.add_provider("second")

        response = self.callback(
            {"email": "a@example.test"},
            provider_id="second",
            provider_in_session="idp",
        )

        self.assert_refused(response, 401)

    def test_callback_without_any_state_is_rejected(self) -> None:
        # Neither side has a state: None == None must not count as a match
        response = self.client.get("/authorize/idp")

        self.assertEqual(response.status_code, 401)
        self.http_post.assert_not_called()

    def test_callback_cannot_be_replayed(self) -> None:
        first = self.callback({"email": "a@example.test"})
        self.assertEqual(first.status_code, 302)

        replay = self.client.get(f"/authorize/idp?state={support.STATE}&code=xyz")

        self.assertEqual(replay.status_code, 401)

    def test_disabled_provider_cannot_complete_a_sign_in(self) -> None:
        self.database.u("update providers set is_enabled = 0")

        response = self.callback({"email": "a@example.test"})

        self.assert_refused(response, 400)

    def test_legacy_callback_url_still_works(self) -> None:
        self.settings.legacy_provider = "idp"

        response = self.callback({"email": "a@example.test"}, path="/authorize")

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.session_user_id())

    def test_legacy_callback_without_a_legacy_provider_is_refused(self) -> None:
        response = self.callback({"email": "a@example.test"}, path="/authorize")

        self.assertEqual(response.status_code, 401)

    def test_sign_in_starts_a_fresh_session(self) -> None:
        with self.client.session_transaction() as session:
            session["leftover"] = "from before sign-in"

        self.callback({"email": "a@example.test"})

        with self.client.session_transaction() as session:
            self.assertNotIn("leftover", session)


class SignedInTests(support.AppTestCase):
    def test_users_cannot_see_each_others_entries(self) -> None:
        self.sign_in_as("alice@example.test")
        self.client.post("/2026/11/10/update", data={"entry-text": "zebrafish party"})
        self.assertIn("zebrafish", self.page("/2026/11/10"))
        found = self.client.post("/search", data={"q": "zebrafish"})
        self.assertIn("zebrafish", found.get_data(as_text=True))

        self.sign_in_as("bob@example.test")
        self.assertNotIn("zebrafish", self.page("/2026/11/10"))
        found = self.client.post("/search", data={"q": "zebrafish"})
        self.assertNotIn("zebrafish", found.get_data(as_text=True))
        # Bob deleting that day must not touch Alice's entry
        self.client.post("/2026/11/10/delete")

        self.sign_in_as("alice@example.test")
        self.assertIn("zebrafish", self.page("/2026/11/10"))

    def test_each_user_gets_a_database_file_named_by_id(self) -> None:
        for email in ("owner@example.test", "other@example.test"):
            self.sign_in_as(email)
            self.assertEqual(self.client.get("/").status_code, 302)

        users = self.database.q("select user_id from users")
        db_files = sorted(p.name for p in (self.data_dir / "users").glob("*.db"))
        self.assertEqual(db_files, sorted(f"{u['user_id']}.db" for u in users))

    def test_email_case_does_not_create_a_second_user(self) -> None:
        self.sign_in_as("Alice@Example.test")
        self.sign_in_as("alice@example.TEST")

        self.assertEqual(self.database.q_val("select count(*) from users"), 1)

    def test_signed_in_pages_have_user_menu_with_sign_out(self) -> None:
        self.sign_in_as("alice@example.test")

        for path in ("/2026/11", "/2026/11/10", "/2026/11/10/edit"):
            with self.subTest(path=path):
                document = lxml.html.fromstring(self.page(path))
                menu = document.xpath("//div[contains(@class, 'dropdown')]")
                self.assertEqual(len(menu), 1)
                self.assertIn("alice@example.test", menu[0].text_content())
                forms = menu[0].xpath(".//form[@action='/sign-out']")
                self.assertEqual(forms[0].get("method"), "post")

    def test_signed_out_pages_have_no_user_menu(self) -> None:
        document = lxml.html.fromstring(self.page("/"))

        self.assertEqual(document.xpath("//div[contains(@class, 'dropdown')]"), [])

    def test_sign_out_clears_session(self) -> None:
        self.sign_in_as("alice@example.test")

        response = self.client.post("/sign-out")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.assertIsNone(self.session_user_id())
        document = lxml.html.fromstring(self.page("/"))
        self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])

    def test_sign_out_requires_post(self) -> None:
        user = self.sign_in_as("alice@example.test")

        self.assertEqual(self.client.get("/sign-out").status_code, 405)
        self.assertEqual(self.session_user_id(), user["user_id"])
