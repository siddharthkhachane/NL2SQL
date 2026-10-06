from functools import lru_cache
from pathlib import Path

from nl2sql import db

DATA = Path(db.DB_PATH).parent
DATABASES = {
    "lahman": DATA / "lahman.sqlite",
    "sakila": DATA / "sakila_master.db",
    "northwind": DATA / "northwind.db",
}
DEFAULT = "lahman"


def available() -> list[str]:
    return [name for name, path in DATABASES.items() if path.exists()]


def path(name: str) -> Path:
    try:
        return DATABASES[name]
    except KeyError:
        raise ValueError(f"unknown database {name!r}; choose from {', '.join(DATABASES)}") from None


@lru_cache(maxsize=None)
def schema(name: str) -> dict:
    return db.get_schema(path(name))


@lru_cache(maxsize=None)
def schema_text(name: str) -> str:
    return db.format_schema(schema(name))
