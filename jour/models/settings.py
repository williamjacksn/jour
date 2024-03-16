import cryptography.fernet
import typing

if typing.TYPE_CHECKING:
    import fort


class Settings:
    def __init__(self, db: 'fort.SQLiteDatabase'):
        self.db = db

    def _get(self, setting_id: str):
        sql = '''
            select setting_value
            from settings
            where setting_id = :setting_id
        '''
        params = {
            'setting_id': setting_id,
        }
        return self.db.q_val(sql, params)

    def _set(self, setting_id: str, setting_value: str):
        sql = '''
            insert into settings (setting_id, setting_value) values (:setting_id, :setting_value)
            on conflict (setting_id) do update set setting_value = excluded.setting_value
        '''
        params = {
            'setting_id': setting_id,
            'setting_value': setting_value,
        }
        self.db.u(sql, params)

    @property
    def caldav_collection_url(self):
        return self.get_str('caldav/collection-url')

    @caldav_collection_url.setter
    def caldav_collection_url(self, value):
        self.set_str('caldav/collection-url', value)

    @property
    def caldav_password(self):
        return self.get_enc('caldav/password')

    @caldav_password.setter
    def caldav_password(self, value):
        self.set_enc('caldav/password', value)

    @property
    def caldav_url(self):
        return self.get_str('caldav/url')

    @caldav_url.setter
    def caldav_url(self, value):
        self.set_str('caldav/url', value)

    @property
    def caldav_username(self):
        return self.get_str('caldav/username')

    @caldav_username.setter
    def caldav_username(self, value):
        self.set_str('caldav/username', value)

    def get_enc(self, setting_id: str):
        val = self._get(setting_id)
        if val:
            f = cryptography.fernet.Fernet(self.secret_key)
            return f.decrypt(val)
        return ''

    def get_str(self, setting_id: str):
        val = self._get(setting_id)
        if val:
            return str(val)
        return ''

    def keys(self) -> set[str]:
        sql = '''
            select setting_id
            from settings
        '''
        return set(row['setting_id'] for row in self.db.q(sql))

    @property
    def openid_client_id(self):
        return self.get_str('openid/client-id')

    @openid_client_id.setter
    def openid_client_id(self, value):
        self.set_str('openid/client-id', value)

    @property
    def openid_client_secret(self):
        return self.get_enc('openid/client-secret')

    @openid_client_secret.setter
    def openid_client_secret(self, value):
        self.set_enc('openid/client-secret', value)

    @property
    def openid_discovery_document(self):
        return self.get_str('openid/discovery-document')

    @openid_discovery_document.setter
    def openid_discovery_document(self, value):
        self.set_str('openid/discovery-document', value)

    @property
    def scheme(self):
        return self.get_str('flask/scheme')

    @scheme.setter
    def scheme(self, value):
        self.set_str('flask/scheme', value)

    @property
    def secret_key(self):
        setting_id = 'flask/secret-key'
        existing_key = self._get(setting_id)
        if existing_key is None:
            self._set(setting_id, cryptography.fernet.Fernet.generate_key().decode())
        return self._get(setting_id)

    def set_enc(self, setting_id: str, setting_value: str):
        f = cryptography.fernet.Fernet(self.secret_key)
        self._set(setting_id, f.encrypt(setting_value.encode()).decode())

    def set_str(self, setting_id: str, setting_value: str):
        self._set(setting_id, setting_value)

    @property
    def user_email(self):
        return self.get_str('user/email')

    @user_email.setter
    def user_email(self, value):
        self.set_str('user/email', value)
