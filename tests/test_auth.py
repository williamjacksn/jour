import datetime as dt
import pathlib
import secrets
import tempfile
import unittest
import urllib.parse
from unittest import mock

import jwt
import jwt.algorithms
import lxml.html
from cryptography.hazmat.primitives.asymmetric import rsa
from werkzeug.test import TestResponse

import jour.app
import jour.models

CLIENT_ID = "test-client"
NONCE = "nonce-123"
ISSUER = "https://identity.example.test/v2.0"
DISCOVERY_URL = "https://identity.example.test/openid"
JWKS_URI = "https://identity.example.test/keys"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_JWK = {
    **jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True),
    "kid": "k1",
}


class AuthenticationTests(unittest.TestCase):
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
        self.settings.admin_email = "owner@example.test"
        self.settings.signup_policy = "open"
        self.http_get = self.enterContext(mock.patch("jour.app.httpx.get"))
        self.http_post = self.enterContext(mock.patch("jour.app.httpx.post"))
        self.http_post.return_value.is_error = False
        self.client = jour.app.app.test_client()

    def sign_in_as(self, email: str) -> None:
        with self.client.session_transaction() as session:
            session["email"] = email

    def page(self, path: str) -> str:
        return self.client.get(path).get_data(as_text=True)

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
        self.sign_in_as("owner@example.test")

        response = self.client.get("/")

        today = dt.datetime.now(tz=dt.UTC).astimezone().date()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], today.strftime("/%Y/%m"))
        self.http_get.assert_not_called()

    def test_any_signed_in_account_gets_its_own_database(self) -> None:
        for email in ("owner@example.test", "other@example.test"):
            self.sign_in_as(email)
            self.assertEqual(self.client.get("/").status_code, 302)

        users = self.database.q("select user_id, email from users order by email")
        self.assertEqual(
            [u["email"] for u in users], ["other@example.test", "owner@example.test"]
        )
        db_files = sorted(p.name for p in (self.data_dir / "users").glob("*.db"))
        self.assertEqual(db_files, sorted(f"{u['user_id']}.db" for u in users))

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

    def test_email_case_does_not_create_a_second_user(self) -> None:
        self.sign_in_as("Alice@Example.test")
        self.client.get("/")
        self.sign_in_as("alice@example.TEST")
        self.client.get("/")

        self.assertEqual(self.database.q_val("select count(*) from users"), 1)

    def test_explicit_sign_in_starts_oauth(self) -> None:
        self.settings.scheme = "http"
        self.settings.openid_client_id = "test-client"
        self.settings.openid_discovery_document = "https://identity.example.test/openid"
        self.http_get.return_value.json.return_value = {
            "authorization_endpoint": "https://identity.example.test/authorize"
        }

        response = self.client.get("/sign-in")

        self.assertEqual(response.status_code, 307)
        location = urllib.parse.urlparse(response.headers["Location"])
        self.assertEqual(location.netloc, "identity.example.test")
        self.assertEqual(location.path, "/authorize")
        query = urllib.parse.parse_qs(location.query)
        self.assertEqual(query["client_id"], ["test-client"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["openid email profile"])
        self.assertEqual(query["redirect_uri"], ["http://localhost/authorize"])
        with self.client.session_transaction() as session:
            self.assertTrue(session["state"])
            self.assertEqual(query["state"], [session["state"]])
            self.assertTrue(session["nonce"])
            self.assertEqual(query["nonce"], [session["nonce"]])
            self.assertNotEqual(session["nonce"], session["state"])
        self.http_get.assert_called_once_with(self.settings.openid_discovery_document)

    def authorize_with_claims(
        self,
        claims: dict,
        *,
        key: rsa.RSAPrivateKey = SIGNING_KEY,
        nonce_in_session: str | None = NONCE,
        state: str = "abc",
    ) -> TestResponse:
        self.settings.scheme = "http"
        self.settings.openid_client_id = CLIENT_ID
        self.settings.openid_discovery_document = DISCOVERY_URL
        documents = {
            DISCOVERY_URL: {
                "token_endpoint": "https://identity.example.test/token",
                "jwks_uri": JWKS_URI,
                "issuer": ISSUER,
                "id_token_signing_alg_values_supported": ["RS256"],
            },
            JWKS_URI: {"keys": [PUBLIC_JWK]},
        }
        self.http_get.side_effect = lambda url, **_: mock.Mock(
            json=lambda: documents[url]
        )
        now = dt.datetime.now(tz=dt.UTC)
        full_claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
            "nonce": NONCE,
            **claims,
        }
        id_token = jwt.encode(
            full_claims, key, algorithm="RS256", headers={"kid": "k1"}
        )
        self.http_post.return_value.json.return_value = {"id_token": id_token}
        with self.client.session_transaction() as session:
            session["state"] = "abc"
            if nonce_in_session is not None:
                session["nonce"] = nonce_in_session
        return self.client.get(f"/authorize?state={state}&code=xyz")

    def test_authorize_stores_normalized_email(self) -> None:
        response = self.authorize_with_claims(
            {"email": "Alice@Example.test", "email_verified": True}
        )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["email"], "alice@example.test")
            self.assertNotIn("state", session)
            self.assertNotIn("nonce", session)

    def test_authorize_rejects_unverified_email(self) -> None:
        response = self.authorize_with_claims(
            {"email": "alice@example.test", "email_verified": False}
        )

        self.assertEqual(response.status_code, 403)
        with self.client.session_transaction() as session:
            self.assertNotIn("email", session)

    def test_authorize_rejects_missing_email(self) -> None:
        response = self.authorize_with_claims({"sub": "123"})

        self.assertEqual(response.status_code, 403)

    def assert_sign_in_rejected(self, response: TestResponse) -> None:
        self.assertEqual(response.status_code, 401)
        with self.client.session_transaction() as session:
            self.assertNotIn("email", session)
        self.assertEqual(self.database.q("select * from users"), [])

    def test_authorize_rejects_token_signed_by_unknown_key(self) -> None:
        response = self.authorize_with_claims(
            {"email": "alice@example.test"}, key=OTHER_KEY
        )

        self.assert_sign_in_rejected(response)

    def test_authorize_rejects_wrong_audience(self) -> None:
        response = self.authorize_with_claims(
            {"email": "alice@example.test", "aud": "another-app"}
        )

        self.assert_sign_in_rejected(response)

    def test_authorize_rejects_wrong_nonce(self) -> None:
        response = self.authorize_with_claims(
            {"email": "alice@example.test", "nonce": "attacker-nonce"}
        )

        self.assert_sign_in_rejected(response)

    def test_authorize_rejects_when_session_has_no_nonce(self) -> None:
        response = self.authorize_with_claims(
            {"email": "alice@example.test"}, nonce_in_session=None
        )

        self.assert_sign_in_rejected(response)

    def test_authorize_rejects_state_mismatch(self) -> None:
        response = self.authorize_with_claims(
            {"email": "alice@example.test"}, state="other"
        )

        self.assert_sign_in_rejected(response)

    def test_authorize_without_any_state_is_rejected(self) -> None:
        # Neither side has a state: None == None must not count as a match
        response = self.client.get("/authorize")

        self.assertEqual(response.status_code, 401)
        self.http_post.assert_not_called()

    def test_authorize_callback_cannot_be_replayed(self) -> None:
        first = self.authorize_with_claims({"email": "alice@example.test"})
        self.assertEqual(first.status_code, 302)

        replay = self.client.get("/authorize?state=abc&code=xyz")

        self.assertEqual(replay.status_code, 401)

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
        with self.client.session_transaction() as session:
            self.assertNotIn("email", session)
        document = lxml.html.fromstring(self.page("/"))
        self.assertEqual(document.xpath("//main//h1/text()"), ["Jour"])

    def test_sign_out_requires_post(self) -> None:
        self.sign_in_as("alice@example.test")

        self.assertEqual(self.client.get("/sign-out").status_code, 405)
        with self.client.session_transaction() as session:
            self.assertEqual(session["email"], "alice@example.test")


if __name__ == "__main__":
    unittest.main()
