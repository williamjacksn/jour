import contextlib
import datetime as dt
import pathlib
import sqlite3
import typing
import uuid

from . import (
    access,
    identities,
    journals,
    paths,
    providers,
    schema,
    settings,
    signin,
    userdb,
    users,
)

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


def _migrate_5(db: fort.SQLiteDatabase) -> None:
    # Track sign-ins, and let an administrator disable an account
    # Check first so a retry after a partial failure is harmless
    have = {row["name"] for row in db.q("select name from pragma_table_info('users')")}
    if "last_sign_in_at" not in have:
        db.u("alter table users add column last_sign_in_at text")
    if "is_disabled" not in have:
        db.u("alter table users add column is_disabled integer not null default 0")


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


def _ensure_user_v3(db: fort.SQLiteDatabase, email: str) -> str:
    """Find or create a user using only the schema as of migration 3.

    Migrations must not call the evolving `users` module, which may expect columns
    added by later migrations.
    """
    email = users.normalize_email(email)
    sql = "select user_id from users where email = :email"
    user_id = db.q_val(sql, {"email": email})
    if user_id is None:
        user_id = str(uuid.uuid4())
        sql = """
            insert into users (user_id, email, created_at)
            values (:user_id, :email, :created_at)
        """
        params = {
            "user_id": user_id,
            "email": email,
            "created_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        }
        db.u(sql, params)
    return user_id


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
            user_db = userdb.open_db(_ensure_user_v3(db, admin_email))
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


def _migrate_6(db: fort.SQLiteDatabase) -> None:
    """Replace the single hard-wired provider with a table of providers.

    Also adds `identities`, which tie a provider's stable subject id to a user, so
    accounts no longer depend on an email address alone.
    """
    db.u("""
        create table if not exists providers (
            provider_id text primary key,
            display_name text not null,
            discovery_document text not null,
            client_id text not null,
            client_secret text not null default '',
            is_enabled integer not null default 1,
            trust_email integer not null default 0
        )
    """)
    db.u("""
        create table if not exists identities (
            provider_id text not null,
            subject text not null,
            user_id text not null,
            created_at text not null,
            primary key (provider_id, subject)
        )
    """)
    db.u("create index if not exists identities_user on identities (user_id)")

    def old(setting_id: str) -> str:
        sql = "select setting_value from settings where setting_id = :id"
        return db.q_val(sql, {"id": setting_id}) or ""

    client_id = old("openid/client-id")
    discovery = old("openid/discovery-document")
    if client_id and discovery:
        is_microsoft = "login.microsoftonline.com" in discovery
        provider_id = "microsoft" if is_microsoft else "oidc"
        sql = """
            insert into providers (
                provider_id, display_name, discovery_document, client_id,
                client_secret, is_enabled, trust_email
            ) values (
                :provider_id, :display_name, :discovery, :client_id, :secret, 1, 1
            ) on conflict (provider_id) do nothing
        """
        params = {
            "provider_id": provider_id,
            "display_name": "Microsoft" if is_microsoft else "Single sign-on",
            "discovery": discovery,
            "client_id": client_id,
            # Already encrypted with the same key, so it can be copied as is
            "secret": old("openid/client-secret"),
        }
        db.u(sql, params)
        # Keep the callback URL registered with the provider working
        sql = """
            insert into settings (setting_id, setting_value)
            values ('signin/legacy-provider', :provider_id)
            on conflict (setting_id) do nothing
        """
        db.u(sql, {"provider_id": provider_id})
    db.u("""
        delete from settings
        where setting_id in (
            'openid/client-id', 'openid/client-secret', 'openid/discovery-document'
        )
    """)


# Append new migrations to the end. Never edit or reorder existing ones.
MIGRATIONS: list[schema.Migration] = [
    _migrate_1,
    _migrate_2,
    _migrate_3,
    _migrate_4,
    _migrate_5,
    _migrate_6,
]


def get_schema_version(db: fort.SQLiteDatabase) -> int:
    return schema.get_version(db)


def init(db: fort.SQLiteDatabase) -> None:
    schema.migrate(db, MIGRATIONS)


__all__ = [
    "access",
    "get_schema_version",
    "identities",
    "init",
    "journals",
    "paths",
    "providers",
    "schema",
    "settings",
    "signin",
    "userdb",
    "users",
]
