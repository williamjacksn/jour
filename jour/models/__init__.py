import typing

from . import journals, settings

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


# Append new migrations to the end. Never edit or reorder existing ones.
# The schema version is the number of migrations applied, stored in
# SQLite's `pragma user_version`.
MIGRATIONS: list[typing.Callable[[fort.SQLiteDatabase], None]] = [
    _migrate_1,
    _migrate_2,
]


def get_schema_version(db: fort.SQLiteDatabase) -> int:
    return int(db.q_val("pragma user_version"))


def init(db: fort.SQLiteDatabase) -> None:
    current = get_schema_version(db)
    if current > len(MIGRATIONS):
        msg = (
            f"Database schema version {current} is newer than this application "
            f"supports ({len(MIGRATIONS)}). Upgrade the application."
        )
        raise RuntimeError(msg)
    for version, migration in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        migration(db)
        # pragma statements cannot take bound parameters; version is our own int
        db.u(f"pragma user_version = {int(version)}")


__all__ = ["get_schema_version", "init", "journals", "settings"]
