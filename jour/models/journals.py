import datetime
import typing

if typing.TYPE_CHECKING:
    import fort


def delete(db: 'fort.SQLiteDatabase', date: datetime.date):
    sql = '''
        delete from journals
        where journal_date = :journal_date
    '''
    params = {
        'journal_date': date,
    }
    db.u(sql, params)


def get_for_date(db: 'fort.SQLiteDatabase', date: datetime.date):
    sql = '''
        select journal_id, journal_date, journal_data
        from journals
        where journal_date = :journal_date
    '''
    params = {
        'journal_date': date,
    }
    return db.q_one(sql, params)


def list_dates_between(db: 'fort.SQLiteDatabase', start: datetime.date, end: datetime.date):
    sql = '''
        select journal_date
        from journals
        where journal_date between :start and :end
    '''
    params = {
        'start': start,
        'end': end,
    }
    return sorted(set(row['journal_date'] for row in db.q(sql, params)))


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
