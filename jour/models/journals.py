import typing

if typing.TYPE_CHECKING:
    import fort


def upsert(db: 'fort.SQLiteDatabase', params: dict):
    sql = '''
        insert into journals (
            journal_id, journal_date, journal_data
        ) values (
            :journal_id, :journal_date, :journal_data
        ) on conflict (journal_id) do update set
            journal_date = excluded.journal_date, journal_data = excluded.journal_data
    '''
    db.u(sql, params)
