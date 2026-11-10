import pathlib
import uuid

DATA_DIR = pathlib.Path(".local")


def app_db_path() -> pathlib.Path:
    return (DATA_DIR / "jour.db").resolve()


def user_db_path(user_id: str) -> pathlib.Path:
    # Round-trip through UUID so only a well-formed id can ever reach the filesystem
    safe_id = uuid.UUID(str(user_id))
    return (DATA_DIR / "users" / f"{safe_id}.db").resolve()
