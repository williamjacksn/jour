import datetime
import typing

if typing.TYPE_CHECKING:
    import fort


def delete(db: 'fort.SQLiteDatabase', date: datetime.date):
    sql = '''
        delete from journal_entries
        where journal_date = :journal_date
    '''
    params = {
        'journal_date': date,
    }
    db.u(sql, params)


def get_for_date(db: 'fort.SQLiteDatabase', date: datetime.date):
    sql = '''
        select journal_id, journal_date, journal_data
        from journal_entries
        where journal_date = :journal_date
    '''
    params = {
        'journal_date': date,
    }
    return db.q_one(sql, params)


def list_dates_between(db: 'fort.SQLiteDatabase', start: datetime.date, end: datetime.date):
    sql = '''
        select distinct journal_date
        from journal_entries
        where journal_date between :start and :end
        order by journal_date
    '''
    params = {
        'start': start,
        'end': end,
    }
    return [datetime.date.fromisoformat(row['journal_date']) for row in db.q(sql, params)]


def upsert(db: 'fort.SQLiteDatabase', params: dict):
    journal_id = params.get('journal_id')
    sql = '''
        select journal_id
        from journal_entries
        where journal_id = :journal_id
    '''
    existing = db.q_one(sql, params)
    if existing:
        db.log.debug(f'Update existing journal entry {journal_id}')
        sql = '''
            update journal_entries
            set journal_date = :journal_date, journal_data = :journal_data
            where journal_id = :journal_id
        '''
    else:
        db.log.debug(f'Insert new journal entry {journal_id}')
        sql = '''
            insert into journal_entries (
                journal_id, journal_date, journal_data
            ) values (
                :journal_id, :journal_date, :journal_data
            )
        '''
    db.u(sql, params)
