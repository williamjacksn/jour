import re
import typing

from . import users

if typing.TYPE_CHECKING:
    from . import settings

POLICY_OPEN = "open"
POLICY_ALLOWLIST = "allowlist"
POLICIES = (POLICY_ALLOWLIST, POLICY_OPEN)


def is_admin(admin_email: str, email: str | None) -> bool:
    if not admin_email or not email:
        return False
    return users.normalize_email(admin_email) == users.normalize_email(email)


def parse_allowlist(text: str) -> set[str]:
    """Split on whitespace and commas; entries are `a@b.c` or `@domain`."""
    return {users.normalize_email(e) for e in re.split(r"[\s,;]+", text) if e}


def signup_allowed(s: settings.Settings, email: str) -> bool:
    """May this person create a new account?

    Anything other than an explicit "open" policy means allowlist, so a missing or
    mistyped setting fails closed.
    """
    email = users.normalize_email(email)
    if is_admin(s.admin_email, email):
        return True
    if s.signup_policy == POLICY_OPEN:
        return True
    entries = parse_allowlist(s.signup_allowlist)
    domain = "@" + email.rpartition("@")[2]
    return email in entries or domain in entries
