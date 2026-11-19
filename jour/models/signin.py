"""Turning a verified ID token into a Jour user."""

import typing

from . import access, identities, users

if typing.TYPE_CHECKING:
    import fort

    from . import settings

type Failure = typing.Literal[
    "no_subject", "no_email", "unverified", "email_in_use", "not_invited"
]


def email_verified(claims: dict) -> bool | None:
    """Normalize the `email_verified` claim: True, False, or None when absent.

    Some providers (Apple) send the strings "true" and "false".
    """
    value = claims.get("email_verified")
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


def resolve_user(
    db: fort.SQLiteDatabase,
    s: settings.Settings,
    provider: dict,
    claims: dict,
) -> tuple[dict | None, Failure | None]:
    """Find, link or create the user for a verified sign-in.

    Returns `(user, None)` on success or `(None, reason)`. Rules:

    - A previously seen (provider, subject) always maps to the same user.
    - Otherwise the email must be acceptable: a claim of false is always refused, and
      a missing claim is accepted only from providers marked `trust_email`.
    - An existing account with that email is linked only if the provider is marked
      `trust_email`; otherwise sign-in is refused, because letting a provider that
      cannot vouch for the address claim it would be an account takeover.
    - A new account must pass the sign-up policy.
    """
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        return None, "no_subject"
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        return None, "no_email"
    verified = email_verified(claims)
    trusted = bool(provider["trust_email"])
    if verified is False or (verified is None and not trusted):
        return None, "unverified"

    provider_id = provider["provider_id"]
    user_id = identities.find_user_id(db, provider_id, subject)
    if user_id is not None:
        user = users.get_by_id(db, user_id)
        if user is not None:
            return user, None

    existing = users.get_by_email(db, email)
    if existing is not None:
        if not trusted:
            return None, "email_in_use"
        identities.link(db, provider_id, subject, existing["user_id"])
        return existing, None

    if not access.signup_allowed(s, email):
        return None, "not_invited"
    user = users.get_or_create(db, email)
    identities.link(db, provider_id, subject, user["user_id"])
    return user, None
