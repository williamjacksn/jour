import contextlib
import pathlib
import sqlite3
import typing

from . import journals, paths, schema, settings, userdb, users

if typing.TYPE_CHECKING:
    import fort


def _migrate_1(db: fort.SQLiteDatabase) -> None:
    # Idempotent so databases created before versioning (user_version 0) upgrade cleanly
    db.u("""
        create table if not exists settings (
            setting_id text primary key,
            setting_value text
        )
    """)
    db.u("""
        create table if not exists journals (
            journal_id uuid primary key,
            journal_date date,
            journal_data blob
        )
    """)


def _migrate_2(db: fort.SQLiteDatabase) -> None:
    # Rename the user/email setting to admin/email
    db.u("""
        update settings
        set setting_id = 'admin/email'
        where setting_id = 'user/email'
        and not exists (select 1 from settings where setting_id = 'admin/email')
    """)
    db.u("delete from settings where setting_id = 'user/email'")


def _migrate_3(db: fort.SQLiteDatabase) -> None:
    # One row per person who has signed in; each owns a separate journal database
    db.u("""
        create table if not exists users (
            user_id text primary key,
            email text not null unique,
            created_at text not null
        )
    """)


def _table_exists(db: fort.SQLiteDatabase, name: str) -> bool:
    sql = """
        select 1
        from sqlite_master
        where type = 'table' and name = :name
    """
    return db.q_val(sql, {"name": name}) is not None


def _backup_app_db(db: fort.SQLiteDatabase) -> None:
    file = db.q_val("select file from pragma_database_list where name = 'main'")
    if not file:
        return
    path = pathlib.Path(file)
    backup = path.with_name(f"{path.name}.pre-multiuser.bak")
    if backup.exists():
        return
    with (
        contextlib.closing(sqlite3.connect(path)) as src,
        contextlib.closing(sqlite3.connect(backup)) as dst,
    ):
        src.backup(dst)


def _migrate_4(db: fort.SQLiteDatabase) -> None:
    # Move the old shared journal into the admin user's own database
    if _table_exists(db, "journal_entries"):
        sql = """
            select journal_id, journal_date, journal_data
            from journal_entries
            order by rowid
        """
        legacy = [dict(row) for row in db.q(sql)]
        if legacy:
            admin_email = settings.Settings(db).admin_email
            if not admin_email:
                msg = (
                    "Existing journal entries must be moved to the admin user's "
                    "database, but admin_email is not set. Run "
                    "`cli.py set admin_email <email>` and try again."
                )
                raise RuntimeError(msg)
            _backup_app_db(db)
            admin = users.get_or_create(db, admin_email)
            user_db = userdb.open_db(admin["user_id"])
            try:
                # Skip anything copied by an earlier, interrupted attempt
                sql = "select journal_id from journal_entries"
                have = {row["journal_id"] for row in user_db.q(sql)}
                sql = """
                    insert into journal_entries (
                        journal_id, journal_date, journal_data
                    ) values (
                        :journal_id, :journal_date, :journal_data
                    )
                """
                user_db.b(sql, [r for r in legacy if r["journal_id"] not in have])
                sql = "select count(*) from journal_entries"
                if user_db.q_val(sql) < len(legacy):
                    msg = "Not all journal entries were copied; aborting migration"
                    raise RuntimeError(msg)
            finally:
                user_db.cnx.close()
        db.u("drop table journal_entries")
    # Unused table from the first schema; only drop it if nothing was ever put in it
    if _table_exists(db, "journals") and db.q_val("select count(*) from journals") == 0:
        db.u("drop table journals")


# Append new migrations to the end. Never edit or reorder existing ones.
MIGRATIONS: list[schema.Migration] = [
    _migrate_1,
    _migrate_2,
    _migrate_3,
    _migrate_4,
]


def get_schema_version(db: fort.SQLiteDatabase) -> int:
    return schema.get_version(db)


def init(db: fort.SQLiteDatabase) -> None:
    schema.migrate(db, MIGRATIONS)


__all__ = [
    "get_schema_version",
    "init",
    "journals",
    "paths",
    "schema",
    "settings",
    "userdb",
    "users",
]
