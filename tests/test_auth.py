import datetime as dt
import secrets
import unittest
import urllib.parse
from unittest import mock

import lxml.html

import jour.app


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(
            mock.patch.dict(
                jour.app.app.config, TESTING=True, SECRET_KEY=secrets.token_hex(32)
            )
        )
        self.database = self.enterContext(mock.patch("jour.app._get_db")).return_value
        self.settings = self.enterContext(
            mock.patch("jour.models.settings.Settings")
        ).return_value
        self.settings.admin_email = "owner@example.test"
        self.http_get = self.enterContext(mock.patch("jour.app.httpx.get"))
        self.client = jour.app.app.test_client()

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
        self.assertEqual(self.database.mock_calls, [])
        with self.client.session_transaction() as session:
            self.assertNotIn("state", session)

    def test_owner_still_goes_to_current_month(self) -> None:
        with self.client.session_transaction() as session:
            session["email"] = self.settings.admin_email

        response = self.client.get("/")

        today = dt.datetime.now(tz=dt.UTC).astimezone().date()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], today.strftime("/%Y/%m"))
        self.http_get.assert_not_called()

    def test_other_accounts_are_still_not_authorized(self) -> None:
        with self.client.session_transaction() as session:
            session["email"] = "other@example.test"

        response = self.client.get("/")

        self.assertIn("Not authorized", response.get_data(as_text=True))
        self.assertNotIn('href="/sign-in"', response.get_data(as_text=True))
        self.assertEqual(self.database.mock_calls, [])
        self.http_get.assert_not_called()

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
        self.http_get.assert_called_once_with(self.settings.openid_discovery_document)


if __name__ == "__main__":
    unittest.main()
