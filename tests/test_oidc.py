import base64
import datetime as dt
import hashlib
import hmac
import json
import unittest
from collections.abc import Callable
from unittest import mock

import jwt
import jwt.algorithms
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import jour.oidc

ISSUER = "https://idp.example.test/v2.0"
CLIENT_ID = "client-123"
NONCE = "nonce-abc"
JWKS_URI = "https://idp.example.test/keys"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(key: rsa.RSAPrivateKey, kid: str) -> dict:
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**public, "kid": kid, "use": "sig", "alg": "RS256"}


def base_claims(**overrides: object) -> dict:
    now = dt.datetime.now(tz=dt.UTC)
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + dt.timedelta(minutes=5),
        "nonce": NONCE,
        "email": "alice@example.test",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def make_token(
    claims: dict, key: rsa.RSAPrivateKey = KEY, kid: str = "k1", alg: str = "RS256"
) -> str:
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge_token(
    header: dict, claims: dict, sign: Callable[[bytes], bytes] | None = None
) -> str:
    """Build a JWT by hand, for algorithms PyJWT refuses to produce."""
    payload = {
        k: int(v.timestamp()) if isinstance(v, dt.datetime) else v
        for k, v in claims.items()
    }
    signing_input = (
        f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}"
    )
    signature = sign(signing_input.encode()) if sign else b""
    return f"{signing_input}.{_b64(signature)}"


class VerifyIdTokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discovery = {
            "issuer": ISSUER,
            "jwks_uri": JWKS_URI,
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        http_get = self.enterContext(mock.patch("jour.oidc.httpx.get"))
        self.http_get = http_get
        http_get.return_value.json.return_value = {"keys": [jwk_for(KEY, "k1")]}

    def verify(self, token: str, nonce: str = NONCE) -> dict:
        return jour.oidc.verify_id_token(
            token,
            discovery_document=self.discovery,
            client_id=CLIENT_ID,
            nonce=nonce,
        )

    def assert_rejected(self, token: str, nonce: str = NONCE) -> None:
        with self.assertRaises(jour.oidc.InvalidIdTokenError):
            self.verify(token, nonce)

    def test_valid_token_returns_claims(self) -> None:
        claims = self.verify(make_token(base_claims()))

        self.assertEqual(claims["email"], "alice@example.test")
        self.http_get.assert_called_once_with(JWKS_URI)

    def test_signature_from_another_key_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(), key=OTHER_KEY))

    def test_tampered_payload_is_rejected(self) -> None:
        header, _, signature = make_token(base_claims()).split(".")
        forged = jwt.api_jws.base64url_encode(
            json.dumps(base_claims(email="admin@example.test"), default=str).encode()
        ).decode()
        self.assert_rejected(f"{header}.{forged}.{signature}")

    def test_unknown_kid_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(), kid="nope"))

    def test_wrong_audience_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(aud="someone-elses-app")))

    def test_wrong_issuer_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(iss="https://evil.example.test")))

    def test_expired_token_is_rejected(self) -> None:
        past = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=1)
        self.assert_rejected(make_token(base_claims(exp=past)))

    def test_small_clock_skew_is_tolerated(self) -> None:
        just_expired = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=10)
        self.verify(make_token(base_claims(exp=just_expired)))

    def test_missing_required_claims_are_rejected(self) -> None:
        for claim in ("exp", "iat", "iss", "aud"):
            with self.subTest(claim=claim):
                self.assert_rejected(make_token(base_claims(**{claim: None})))

    def test_wrong_nonce_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(nonce="other")))

    def test_missing_nonce_claim_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(nonce=None)))

    def test_empty_expected_nonce_is_rejected(self) -> None:
        self.assert_rejected(make_token(base_claims(nonce="")), nonce="")

    def test_unsigned_token_is_rejected(self) -> None:
        self.discovery["id_token_signing_alg_values_supported"] = ["none", "RS256"]
        token = forge_token({"alg": "none", "kid": "k1"}, base_claims())
        self.assert_rejected(token)

    def test_symmetric_algorithm_confusion_is_rejected(self) -> None:
        # Attacker signs with HMAC using the provider's public key as the secret
        self.discovery["id_token_signing_alg_values_supported"] = ["HS256", "RS256"]
        public_pem = KEY.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        token = forge_token(
            {"alg": "HS256", "kid": "k1"},
            base_claims(),
            sign=lambda data: hmac.new(public_pem, data, hashlib.sha256).digest(),
        )
        self.assert_rejected(token)

    def test_algorithm_not_advertised_by_provider_is_rejected(self) -> None:
        self.discovery["id_token_signing_alg_values_supported"] = ["ES256"]
        self.assert_rejected(make_token(base_claims()))

    def test_garbage_is_rejected(self) -> None:
        self.assert_rejected("not-a-jwt")
        self.assert_rejected("")

    def test_discovery_document_without_jwks_uri_is_rejected(self) -> None:
        del self.discovery["jwks_uri"]
        self.assert_rejected(make_token(base_claims()))

    def test_discovery_document_without_issuer_is_rejected(self) -> None:
        del self.discovery["issuer"]
        self.assert_rejected(make_token(base_claims()))


class MultiTenantIssuerTests(unittest.TestCase):
    TID = "9188040d-6c67-4c5b-b112-36a304b66dad"

    def setUp(self) -> None:
        self.discovery = {
            "issuer": "https://login.example.test/{tenantid}/v2.0",
            "jwks_uri": JWKS_URI,
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        http_get = self.enterContext(mock.patch("jour.oidc.httpx.get"))
        http_get.return_value.json.return_value = {"keys": [jwk_for(KEY, "k1")]}

    def verify(self, claims: dict) -> dict:
        return jour.oidc.verify_id_token(
            make_token(claims),
            discovery_document=self.discovery,
            client_id=CLIENT_ID,
            nonce=NONCE,
        )

    def test_placeholder_is_filled_from_tid(self) -> None:
        iss = f"https://login.example.test/{self.TID}/v2.0"

        claims = self.verify(base_claims(iss=iss, tid=self.TID))

        self.assertEqual(claims["tid"], self.TID)

    def test_iss_for_a_different_tenant_than_tid_is_rejected(self) -> None:
        iss = "https://login.example.test/11111111-1111-1111-1111-111111111111/v2.0"

        with self.assertRaises(jour.oidc.InvalidIdTokenError):
            self.verify(base_claims(iss=iss, tid=self.TID))

    def test_missing_or_malformed_tid_is_rejected(self) -> None:
        for tid in (None, "../../x", 5):
            with self.subTest(tid=tid):
                iss = f"https://login.example.test/{tid}/v2.0"
                with self.assertRaises(jour.oidc.InvalidIdTokenError):
                    self.verify(base_claims(iss=iss, tid=tid))


if __name__ == "__main__":
    unittest.main()
