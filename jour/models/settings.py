import dataclasses
import typing

import cryptography.fernet

if typing.TYPE_CHECKING:
    import fort


@dataclasses.dataclass(frozen=True)
class SettingDef:
    name: str  # attribute / CLI name
    setting_id: str  # key in the settings table
    description: str
    encrypted: bool = False  # stored encrypted and hidden in CLI output


REGISTRY: dict[str, SettingDef] = {
    d.name: d
    for d in (
        SettingDef(
            "openid_client_id",
            "openid/client-id",
            "OpenID Connect client ID",
        ),
        SettingDef(
            "openid_client_secret",
            "openid/client-secret",
            "OpenID Connect client secret",
            encrypted=True,
        ),
        SettingDef(
            "openid_discovery_document",
            "openid/discovery-document",
            "URL of the OpenID Connect discovery document",
        ),
        SettingDef(
            "scheme",
            "flask/scheme",
            "URL scheme (http or https) used to build the redirect URI",
        ),
        SettingDef(
            "admin_email",
            "admin/email",
            "Email address of the administrator",
        ),
        SettingDef(
            "signup_policy",
            "signup/policy",
            "Who may create an account on first sign-in: open or allowlist",
        ),
        SettingDef(
            "signup_allowlist",
            "signup/allowlist",
            "Emails and @domains allowed to sign up when the policy is allowlist",
        ),
    )
}


class Settings:
    def __init__(self, db: fort.SQLiteDatabase) -> None:
        self.db = db

    def get_by_name(self, name: str) -> str:
        """Get a registered setting by its registry name."""
        d = REGISTRY[name]
        if d.encrypted:
            return self.get_enc(d.setting_id).decode()
        return self.get_str(d.setting_id)

    def set_by_name(self, name: str, value: str) -> None:
        """Set a registered setting by its registry name."""
        d = REGISTRY[name]
        if d.encrypted:
            self.set_enc(d.setting_id, value)
        else:
            self.set_str(d.setting_id, value)

    def _get(self, setting_id: str) -> typing.Any:  # noqa: ANN401
        sql = """
            select setting_value
            from settings
            where setting_id = :setting_id
        """
        params = {
            "setting_id": setting_id,
        }
        return self.db.q_val(sql, params)

    def _set(self, setting_id: str, setting_value: str) -> None:
        sql = """
            insert into settings (
                setting_id, setting_value
            ) values (
                :setting_id, :setting_value
            ) on conflict (setting_id) do update set
                setting_value = excluded.setting_value
        """
        params = {
            "setting_id": setting_id,
            "setting_value": setting_value,
        }
        self.db.u(sql, params)

    def get_enc(self, setting_id: str) -> bytes:
        val = self._get(setting_id)
        if val:
            f = cryptography.fernet.Fernet(self.secret_key)
            return f.decrypt(val)
        return b""

    def get_str(self, setting_id: str) -> str:
        val = self._get(setting_id)
        if val:
            return str(val)
        return ""

    def keys(self) -> set[str]:
        sql = """
            select setting_id
            from settings
        """
        return {row["setting_id"] for row in self.db.q(sql)}

    @property
    def openid_client_id(self) -> str:
        return self.get_str("openid/client-id")

    @openid_client_id.setter
    def openid_client_id(self, value: str) -> None:
        self.set_str("openid/client-id", value)

    @property
    def openid_client_secret(self) -> str:
        return self.get_enc("openid/client-secret").decode()

    @openid_client_secret.setter
    def openid_client_secret(self, value: str) -> None:
        self.set_enc("openid/client-secret", value)

    @property
    def openid_discovery_document(self) -> str:
        return self.get_str("openid/discovery-document")

    @openid_discovery_document.setter
    def openid_discovery_document(self, value: str) -> None:
        self.set_str("openid/discovery-document", value)

    @property
    def scheme(self) -> str:
        return self.get_str("flask/scheme")

    @scheme.setter
    def scheme(self, value: str) -> None:
        self.set_str("flask/scheme", value)

    @property
    def secret_key(self) -> str:
        setting_id = "flask/secret-key"
        existing_key = self._get(setting_id)
        if existing_key is None:
            self._set(setting_id, cryptography.fernet.Fernet.generate_key().decode())
        return self._get(setting_id)

    def set_enc(self, setting_id: str, setting_value: str) -> None:
        f = cryptography.fernet.Fernet(self.secret_key)
        self._set(setting_id, f.encrypt(setting_value.encode()).decode())

    def set_str(self, setting_id: str, setting_value: str) -> None:
        self._set(setting_id, setting_value)

    @property
    def admin_email(self) -> str:
        return self.get_str("admin/email")

    @admin_email.setter
    def admin_email(self, value: str) -> None:
        self.set_str("admin/email", value)

    @property
    def signup_allowlist(self) -> str:
        return self.get_str("signup/allowlist")

    @signup_allowlist.setter
    def signup_allowlist(self, value: str) -> None:
        self.set_str("signup/allowlist", value)

    @property
    def signup_policy(self) -> str:
        return self.get_str("signup/policy")

    @signup_policy.setter
    def signup_policy(self, value: str) -> None:
        self.set_str("signup/policy", value)
