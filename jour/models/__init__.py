import typing

from . import journals, settings

if typing.TYPE_CHECKING:
    import fort


def init(db: fort.SQLiteDatabase) -> None:
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


__all__ = [init, journals, settings]
