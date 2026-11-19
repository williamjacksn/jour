"""Sign-in providers: the OpenID Connect identity providers an admin configured."""

import re
import typing
import urllib.parse

if typing.TYPE_CHECKING:
    import fort

    from . import settings


class Preset(typing.NamedTuple):
    display_name: str
    discovery_document: str
    trust_email: bool


PRESETS: dict[str, Preset] = {
    "google": Preset(
        "Google",
        "https://accounts.google.com/.well-known/openid-configuration",
        trust_email=True,
    ),
    "microsoft": Preset(
        "Microsoft",
        "https://login.microsoftonline.com/consumers/v2.0/.well-known/openid-configuration",
        trust_email=True,
    ),
}

ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,31}")
# Used in URLs as /admin/providers/new
RESERVED_IDS = frozenset({"new"})


def get(db: fort.SQLiteDatabase, provider_id: str) -> dict | None:
    sql = """
        select provider_id, display_name, discovery_document, client_id,
            client_secret, is_enabled, trust_email
        from providers
        where provider_id = :provider_id
    """
    return db.q_one(sql, {"provider_id": provider_id})


def list_all(db: fort.SQLiteDatabase) -> list[dict]:
    sql = """
        select provider_id, display_name, discovery_document, client_id,
            client_secret, is_enabled, trust_email
        from providers
        order by display_name, provider_id
    """
    return db.q(sql)


def list_enabled(db: fort.SQLiteDatabase) -> list[dict]:
    return [p for p in list_all(db) if p["is_enabled"]]


def client_secret(s: settings.Settings, provider: dict) -> str:
    return s.decrypt(provider["client_secret"])


def validate(
    provider_id: str,
    *,
    display_name: str,
    discovery_document: str,
    client_id: str,
    has_secret: bool,
) -> list[str]:
    errors: list[str] = []
    if not ID_PATTERN.fullmatch(provider_id) or provider_id in RESERVED_IDS:
        errors.append(
            "ID must be lowercase letters, digits and hyphens, starting with a letter."
        )
    if not display_name:
        errors.append("Name is required.")
    parsed = urllib.parse.urlparse(discovery_document)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors.append("Discovery document must be an http or https URL.")
    if not client_id:
        errors.append("Client ID is required.")
    if not has_secret:
        errors.append("Client secret is required.")
    return errors


def save(
    db: fort.SQLiteDatabase,
    s: settings.Settings,
    provider_id: str,
    *,
    display_name: str,
    discovery_document: str,
    client_id: str,
    secret: str | None,
    is_enabled: bool,
    trust_email: bool,
) -> None:
    """Create or update a provider. `secret=None` keeps the stored secret."""
    existing = get(db, provider_id)
    if secret:
        stored_secret = s.encrypt(secret)
    elif existing:
        stored_secret = existing["client_secret"]
    else:
        stored_secret = ""
    sql = """
        insert into providers (
            provider_id, display_name, discovery_document, client_id,
            client_secret, is_enabled, trust_email
        ) values (
            :provider_id, :display_name, :discovery_document, :client_id,
            :client_secret, :is_enabled, :trust_email
        ) on conflict (provider_id) do update set
            display_name = excluded.display_name,
            discovery_document = excluded.discovery_document,
            client_id = excluded.client_id,
            client_secret = excluded.client_secret,
            is_enabled = excluded.is_enabled,
            trust_email = excluded.trust_email
    """
    params = {
        "provider_id": provider_id,
        "display_name": display_name,
        "discovery_document": discovery_document,
        "client_id": client_id,
        "client_secret": stored_secret,
        "is_enabled": int(is_enabled),
        "trust_email": int(trust_email),
    }
    db.u(sql, params)


def delete(db: fort.SQLiteDatabase, provider_id: str) -> None:
    db.u("delete from providers where provider_id = :id", {"id": provider_id})
