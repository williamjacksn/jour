"""Validation of OpenID Connect ID tokens (OpenID Connect Core 1.0, section 3.1.3.7)."""

import hmac
import re
import typing

import httpx
import jwt

# Asymmetric only: an HS* or "none" token could be forged by anyone
ALLOWED_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
    }
)
CLOCK_LEEWAY_SECONDS = 60
TENANT_PLACEHOLDER = "{tenantid}"
GUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class InvalidIdTokenError(Exception):
    """The ID token cannot be trusted."""


def _find_key(discovery_document: dict, kid: str | None) -> jwt.PyJWK:
    jwks_uri = discovery_document.get("jwks_uri")
    if not jwks_uri:
        msg = "Discovery document has no jwks_uri"
        raise InvalidIdTokenError(msg)
    response = httpx.get(jwks_uri)
    response.raise_for_status()
    try:
        key_set = jwt.PyJWKSet.from_dict(response.json())
    except (jwt.PyJWTError, ValueError) as e:
        msg = f"Could not read signing keys: {e}"
        raise InvalidIdTokenError(msg) from e
    for key in key_set.keys:
        if key.key_id == kid:
            return key
    msg = f"No signing key with kid {kid!r}"
    raise InvalidIdTokenError(msg)


def _expected_issuer(discovery_document: dict, id_token: str) -> str:
    issuer = discovery_document.get("issuer")
    if not issuer:
        msg = "Discovery document has no issuer"
        raise InvalidIdTokenError(msg)
    if TENANT_PLACEHOLDER in issuer:
        # Multi-tenant Microsoft endpoints: the issuer names the tenant that signed in.
        # The signature check still has to pass, and the result must equal `iss`.
        tid = jwt.decode(id_token, options={"verify_signature": False}).get("tid")
        if not isinstance(tid, str) or not GUID.fullmatch(tid):
            msg = "ID token has no valid tid claim"
            raise InvalidIdTokenError(msg)
        issuer = issuer.replace(TENANT_PLACEHOLDER, tid)
    return issuer


def verify_id_token(
    id_token: str,
    *,
    discovery_document: dict,
    client_id: str,
    nonce: str,
) -> dict[str, typing.Any]:
    """Return the claims of a valid ID token, or raise InvalidIdTokenError.

    Checks the signature against the provider's published keys, then `iss`, `aud`,
    `exp`, `iat` and `nonce`.
    """
    if not nonce:
        msg = "No nonce to check against"
        raise InvalidIdTokenError(msg)
    try:
        header = jwt.get_unverified_header(id_token)
        algorithm = header.get("alg")
        advertised = discovery_document.get("id_token_signing_alg_values_supported", [])
        if algorithm not in ALLOWED_ALGORITHMS or algorithm not in advertised:
            msg = f"Unacceptable signing algorithm {algorithm!r}"
            raise InvalidIdTokenError(msg)
        key = _find_key(discovery_document, header.get("kid"))
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=[algorithm],
            audience=client_id,
            issuer=_expected_issuer(discovery_document, id_token),
            leeway=CLOCK_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        msg = f"Invalid ID token: {e}"
        raise InvalidIdTokenError(msg) from e
    claim_nonce = claims.get("nonce")
    if not isinstance(claim_nonce, str) or not hmac.compare_digest(claim_nonce, nonce):
        msg = "Nonce does not match"
        raise InvalidIdTokenError(msg)
    return claims
