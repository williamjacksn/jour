import contextlib
import sqlite3

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


def stats(user_id: str) -> tuple[int | None, int]:
    """Return (entry count, file size in bytes) without creating anything."""
    path = paths.user_db_path(user_id)
    if not path.exists():
        return 0, 0
    size = path.stat().st_size
    try:
        with contextlib.closing(
            sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        ) as c:
            count = c.execute("select count(*) from journal_entries").fetchone()[0]
    except sqlite3.Error:
        return None, size
    return count, size


def delete_files(user_id: str) -> None:
    """Remove a user's database and any SQLite side files."""
    path = paths.user_db_path(user_id)
    for suffix in ("", "-wal", "-shm", "-journal"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
