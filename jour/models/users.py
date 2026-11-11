import datetime as dt
import typing
import uuid

if typing.TYPE_CHECKING:
    import fort


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat()


def get_by_email(db: fort.SQLiteDatabase, email: str) -> dict | None:
    sql = """
        select user_id, email, created_at, last_sign_in_at, is_disabled
        from users
        where email = :email
    """
    return db.q_one(sql, {"email": normalize_email(email)})


def get_by_id(db: fort.SQLiteDatabase, user_id: str) -> dict | None:
    sql = """
        select user_id, email, created_at, last_sign_in_at, is_disabled
        from users
        where user_id = :user_id
    """
    return db.q_one(sql, {"user_id": user_id})


def list_all(db: fort.SQLiteDatabase) -> list[dict]:
    sql = """
        select user_id, email, created_at, last_sign_in_at, is_disabled
        from users
        order by email
    """
    return db.q(sql)


def get_or_create(db: fort.SQLiteDatabase, email: str) -> dict:
    existing = get_by_email(db, email)
    if existing:
        return existing
    now = _now()
    sql = """
        insert into users (
            user_id, email, created_at, last_sign_in_at
        ) values (
            :user_id, :email, :now, :now
        ) on conflict (email) do nothing
    """
    params = {
        "user_id": str(uuid.uuid4()),
        "email": normalize_email(email),
        "now": now,
    }
    db.u(sql, params)
    # Re-read so concurrent first sign-ins agree on a single user_id
    created = get_by_email(db, email)
    if created is None:  # pragma: no cover
        msg = "Could not create user"
        raise RuntimeError(msg)
    return created


def record_sign_in(db: fort.SQLiteDatabase, email: str) -> None:
    sql = """
        update users
        set last_sign_in_at = :now
        where email = :email
    """
    db.u(sql, {"now": _now(), "email": normalize_email(email)})


def set_disabled(db: fort.SQLiteDatabase, user_id: str, *, disabled: bool) -> None:
    sql = """
        update users
        set is_disabled = :is_disabled
        where user_id = :user_id
    """
    db.u(sql, {"is_disabled": int(disabled), "user_id": user_id})


def delete(db: fort.SQLiteDatabase, user_id: str) -> None:
    db.u("delete from users where user_id = :user_id", {"user_id": user_id})
