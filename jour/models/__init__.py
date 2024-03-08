from . import settings

import typing

if typing.TYPE_CHECKING:
    import fort


def init(db: 'fort.SQLiteDatabase'):
    db.u('''
        create table if not exists settings (
            setting_id text primary key,
            setting_value text
        )
    ''')
    db.u('''
        create table if not exists journals (
            journal_id uuid primary key,
            journal_date date,
            journal_data text
        )
    ''')
