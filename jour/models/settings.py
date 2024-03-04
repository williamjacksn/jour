import cryptography.fernet
import typing

if typing.TYPE_CHECKING:
    import fort


def _get(db: 'fort.SqliteDatabase', setting_id: str):
    sql = '''
        select setting_value
        from settings
        where setting_id = :setting_id
    '''
    params = {
        'setting_id': setting_id,
    }
    return db.q_val(sql, params)


def _set(db: 'fort.SqliteDatabase', setting_id: str, setting_value: str):
    sql = '''
        insert into settings (setting_id, setting_value) values (:setting_id, :setting_value)
        on conflict (setting_id) do update set setting_value = excluded.setting_value
    '''
    params = {
        'setting_id': setting_id,
        'setting_value': setting_value,
    }
    db.u(sql, params)


def get_enc(db: 'fort.SqliteDatabase', setting_id: str):
    val = _get(db, setting_id)
    if val:
        f = cryptography.fernet.Fernet(secret_key(db))
        return f.decrypt(val)
    return ''


def get_str(db: 'fort.SqliteDatabase', setting_id: str):
    val = _get(db, setting_id)
    if val:
        return str(val)
    return ''


def secret_key(db: 'fort.SQLiteDatabase'):
    setting_id = 'flask/secret-key'
    secret_key = _get(db, setting_id)
    if secret_key is None:
        _set(db, setting_id, cryptography.fernet.Fernet.generate_key().decode())
    return _get(db, setting_id)


def set_enc(db: 'fort.SqliteDatabase', setting_id: str, setting_value: str):
    f = cryptography.fernet.Fernet(secret_key(db))
    _set(db, setting_id, f.encrypt(setting_value.encode()))


def set_str(db: 'fort.SqliteDatabase', setting_id: str, setting_value: str):
    _set(db, setting_id, setting_value)
