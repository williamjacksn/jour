import datetime
import typing

if typing.TYPE_CHECKING:
    import fort


def delete(db: "fort.SQLiteDatabase", date: datetime.date) -> None:
    sql = """
        delete from journal_entries
        where journal_date = :journal_date
    """
    params = {
        "journal_date": date,
    }
    db.u(sql, params)


def get_for_date(db: "fort.SQLiteDatabase", date: datetime.date) -> dict:
    sql = """
        select journal_id, journal_date, journal_data
        from journal_entries
        where journal_date = :journal_date
    """
    params = {
        "journal_date": date,
    }
    return db.q_one(sql, params)


def list_dates_between(
    db: "fort.SQLiteDatabase", start: datetime.date, end: datetime.date
) -> list[datetime.date]:
    sql = """
        select distinct journal_date
        from journal_entries
        where journal_date between :start and :end
        order by journal_date
    """
    params = {
        "start": start,
        "end": end,
    }
    return [
        datetime.date.fromisoformat(row["journal_date"]) for row in db.q(sql, params)
    ]


def search(db: "fort.SQLiteDatabase", q: str, page: int = 1) -> list[dict]:
    sql = """
        select
            journal_data, journal_date, printf('%.2f', rank * -1) score,
            snippet(journal_entries, 2, '', '', ' ... ', 16) snip
        from journal_entries
        where journal_entries match :q
        order by rank, journal_id
        limit 11 offset :offset
    """
    params = {
        "q": q,
        "offset": 10 * (page - 1),
    }
    return [
        {
            "journal_date": datetime.date.fromisoformat(row["journal_date"]),
            "score": row["score"],
            "snip": row["snip"],
        }
        for row in db.q(sql, params)
    ]


def upsert(db: "fort.SQLiteDatabase", params: dict) -> None:
    journal_id = params.get("journal_id")
    sql = """
        select journal_id
        from journal_entries
        where journal_id = :journal_id
    """
    existing = db.q_one(sql, params)
    if existing:
        db.log.debug(f"Update existing journal entry {journal_id}")
        sql = """
            update journal_entries
            set journal_date = :journal_date, journal_data = :journal_data
            where journal_id = :journal_id
        """
    else:
        db.log.debug(f"Insert new journal entry {journal_id}")
        sql = """
            insert into journal_entries (
                journal_id, journal_date, journal_data
            ) values (
                :journal_id, :journal_date, :journal_data
            )
        """
    db.u(sql, params)
