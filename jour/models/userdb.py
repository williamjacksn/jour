import fort

from . import paths, schema


def _migrate_1(db: fort.SQLiteDatabase) -> None:
    db.u("""
        create virtual table if not exists journal_entries
        using fts5(journal_id unindexed, journal_date, journal_data)
    """)


MIGRATIONS: list[schema.Migration] = [
    _migrate_1,
]


def init(db: fort.SQLiteDatabase) -> None:
    schema.migrate(db, MIGRATIONS)


def open_db(user_id: str) -> fort.SQLiteDatabase:
    """Open (creating and upgrading if needed) the database for one user."""
    path = paths.user_db_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = fort.SQLiteDatabase(str(path))
    init(db)
    return db
