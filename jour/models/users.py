import datetime as dt
import typing
import uuid

if typing.TYPE_CHECKING:
    import fort


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_email(db: fort.SQLiteDatabase, email: str) -> dict | None:
    sql = """
        select user_id, email, created_at
        from users
        where email = :email
    """
    return db.q_one(sql, {"email": normalize_email(email)})


def get_or_create(db: fort.SQLiteDatabase, email: str) -> dict:
    existing = get_by_email(db, email)
    if existing:
        return existing
    sql = """
        insert into users (
            user_id, email, created_at
        ) values (
            :user_id, :email, :created_at
        ) on conflict (email) do nothing
    """
    params = {
        "user_id": str(uuid.uuid4()),
        "email": normalize_email(email),
        "created_at": dt.datetime.now(tz=dt.UTC).isoformat(),
    }
    db.u(sql, params)
    # Re-read so concurrent first sign-ins agree on a single user_id
    created = get_by_email(db, email)
    if created is None:  # pragma: no cover
        msg = "Could not create user"
        raise RuntimeError(msg)
    return created
