from . import settings

import typing

if typing.TYPE_CHECKING:
    import fort


def init(db: 'fort.SqliteDatabase'):
    sql = '''
        create table if not exists settings (
            setting_id text primary key,
            setting_value text
        )
    '''
    db.u(sql)
