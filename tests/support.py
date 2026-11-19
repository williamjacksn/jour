"""Shared fixtures: a temporary data directory, real databases and a fake provider.

The fake provider signs real RS256 ID tokens, so the code under test goes through
the same verification path as in production. Only the HTTP calls are mocked.
"""

import datetime as dt
import pathlib
import secrets
import tempfile
import unittest
from unittest import mock

import jwt
import jwt.algorithms
from cryptography.hazmat.primitives.asymmetric import rsa
from werkzeug.test import TestResponse

import jour.app
import jour.models

CLIENT_ID = "test-client"
NONCE = "nonce-123"
STATE = "state-123"
ADMIN = "owner@example.test"

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_JWK = {
    **jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True),
    "kid": "k1",
}


def discovery_url(provider_id: str) -> str:
    return f"https://{provider_id}.example.test/.well-known/openid-configuration"


def issuer(provider_id: str) -> str:
    return f"https://{provider_id}.example.test"


class AppTestCase(unittest.TestCase):
    """Fresh databases and a signed-in-capable client for every test."""

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
        self.settings.scheme = "https"
        self.settings.signup_policy = "open"

        self.documents: dict[str, dict] = {}
        self.http_get = self.enterContext(mock.patch("jour.app.httpx.get"))
        self.http_get.side_effect = lambda url, **_: mock.Mock(
            json=lambda: self.documents[url]
        )
        self.http_post = self.enterContext(mock.patch("jour.app.httpx.post"))
        self.http_post.return_value.is_error = False
        self.add_provider("idp")
        self.client = jour.app.app.test_client()

    def add_provider(
        self,
        provider_id: str,
        *,
        trust_email: bool = True,
        enabled: bool = True,
        display_name: str | None = None,
    ) -> None:
        """Register a provider in the database and teach the HTTP mock about it."""
        jour.models.providers.save(
            self.database,
            self.settings,
            provider_id,
            display_name=display_name or provider_id.title(),
            discovery_document=discovery_url(provider_id),
            client_id=CLIENT_ID,
            secret="provider-secret",  # noqa: S106
            is_enabled=enabled,
            trust_email=trust_email,
        )
        base = issuer(provider_id)
        self.documents[discovery_url(provider_id)] = {
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "jwks_uri": f"{base}/keys",
            "issuer": base,
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        self.documents[f"{base}/keys"] = {"keys": [PUBLIC_JWK]}

    def make_user(self, email: str) -> dict:
        """Create a user with a journal entry, as if they had signed in before."""
        user = jour.models.users.get_or_create(self.database, email)
        user_db = jour.models.userdb.open_db(user["user_id"])
        user_db.u("insert into journal_entries values ('1', '2026-11-10', 'hello')")
        user_db.cnx.close()
        return user

    def sign_in_as(self, email: str) -> dict:
        """Put an existing (or new) user's id in the session, skipping the provider."""
        user = jour.models.users.get_or_create(self.database, email)
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user["user_id"]
        return user

    def callback(
        self,
        claims: dict,
        *,
        provider_id: str = "idp",
        path: str | None = None,
        key: rsa.RSAPrivateKey = SIGNING_KEY,
        nonce_in_session: str | None = NONCE,
        state_in_session: str | None = STATE,
        state_in_request: str = STATE,
        provider_in_session: str | None = None,
    ) -> TestResponse:
        """Complete the provider's redirect back to us with an ID token for `claims`."""
        now = dt.datetime.now(tz=dt.UTC)
        email = claims.get("email", "nobody")
        full_claims = {
            "iss": issuer(provider_id),
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
            "nonce": NONCE,
            "sub": f"sub-{email}",
            **claims,
        }
        id_token = jwt.encode(
            full_claims, key, algorithm="RS256", headers={"kid": "k1"}
        )
        self.http_post.return_value.json.return_value = {"id_token": id_token}
        with self.client.session_transaction() as session:
            if state_in_session is not None:
                session["state"] = state_in_session
            if nonce_in_session is not None:
                session["nonce"] = nonce_in_session
            session["provider"] = provider_in_session or provider_id
        url = path or f"/authorize/{provider_id}"
        return self.client.get(f"{url}?state={state_in_request}&code=xyz")

    def session_user_id(self) -> str | None:
        with self.client.session_transaction() as session:
            return session.get("user_id")

    def page(self, path: str) -> str:
        return self.client.get(path).get_data(as_text=True)
