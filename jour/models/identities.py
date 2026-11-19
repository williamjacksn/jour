"""Links between a provider's stable subject id and a Jour user."""

import datetime as dt
import typing

if typing.TYPE_CHECKING:
    import fort


def find_user_id(db: fort.SQLiteDatabase, provider_id: str, subject: str) -> str | None:
    sql = """
        select user_id
        from identities
        where provider_id = :provider_id and subject = :subject
    """
    return db.q_val(sql, {"provider_id": provider_id, "subject": subject})


def link(db: fort.SQLiteDatabase, provider_id: str, subject: str, user_id: str) -> None:
    sql = """
        insert into identities (
            provider_id, subject, user_id, created_at
        ) values (
            :provider_id, :subject, :user_id, :created_at
        ) on conflict (provider_id, subject) do update set
            user_id = excluded.user_id
    """
    params = {
        "provider_id": provider_id,
        "subject": subject,
        "user_id": user_id,
        "created_at": dt.datetime.now(tz=dt.UTC).isoformat(),
    }
    db.u(sql, params)


def count_by_provider(db: fort.SQLiteDatabase) -> dict[str, int]:
    sql = """
        select provider_id, count(*) n
        from identities
        group by provider_id
    """
    return {row["provider_id"]: row["n"] for row in db.q(sql)}


def providers_for_user(db: fort.SQLiteDatabase, user_id: str) -> list[str]:
    sql = """
        select provider_id
        from identities
        where user_id = :user_id
        order by provider_id
    """
    return [row["provider_id"] for row in db.q(sql, {"user_id": user_id})]
