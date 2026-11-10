import typing

if typing.TYPE_CHECKING:
    import fort

type Migration = typing.Callable[[fort.SQLiteDatabase], None]


def get_version(db: fort.SQLiteDatabase) -> int:
    return int(db.q_val("pragma user_version"))


def migrate(db: fort.SQLiteDatabase, migrations: list[Migration]) -> None:
    """Apply any migrations the database has not seen yet.

    The schema version is the number of migrations applied, stored in SQLite's
    `pragma user_version`. Never edit or reorder existing migrations.
    """
    current = get_version(db)
    if current > len(migrations):
        msg = (
            f"Database schema version {current} is newer than this application "
            f"supports ({len(migrations)}). Upgrade the application."
        )
        raise RuntimeError(msg)
    for version, migration in enumerate(migrations, start=1):
        if version <= current:
            continue
        migration(db)
        # pragma statements cannot take bound parameters; version is our own int
        db.u(f"pragma user_version = {int(version)}")
