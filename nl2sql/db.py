import re
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "lahman.sqlite"
DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT = 10.0

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")
_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


class UnsafeSQL(ValueError):
    pass


def tables_in(sql: str) -> set[str]:
    """Lower-case table names after FROM/JOIN (a rough scan; fine for display and eval tagging)."""
    return {t.lower() for t in re.findall(r"\b(?:from|join)\s+\"?(\w+)", sql or "", re.IGNORECASE)}


def connect(path=None) -> sqlite3.Connection:
    uri = f"file:{Path(path or DB_PATH).as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def validate_sql(sql: str) -> str:
    """Return the cleaned statement, or raise UnsafeSQL."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        raise UnsafeSQL("empty query")
    code = _STRING_LITERAL.sub("''", stripped)
    if ";" in code:
        raise UnsafeSQL("multiple statements are not allowed")
    if "--" in code or "/*" in code or "*/" in code:
        raise UnsafeSQL("comments are not allowed")
    if code.split(None, 1)[0].upper() not in ("SELECT", "WITH"):
        raise UnsafeSQL("only SELECT statements are allowed")
    return stripped


def execute_safe(sql: str, limit: int = DEFAULT_LIMIT, timeout: float = DEFAULT_TIMEOUT, path=None):
    """Run a validated SELECT read-only. Returns (columns, rows). Raises UnsafeSQL or sqlite3.Error."""
    sql = validate_sql(sql)
    conn = connect(path)
    try:
        conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY)
        deadline = time.monotonic() + timeout
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
        cur = conn.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit)
        return columns, rows
    finally:
        conn.close()


def _short(value, limit: int = 60):
    return value[:limit] + "..." if isinstance(value, str) and len(value) > limit else value


def quote_name(name: str) -> str:
    return name if name.isidentifier() else '"' + name + '"'


def get_schema(path=None, samples: int = 3) -> dict:
    """{table: [{name, type, samples}]} with up to `samples` distinct values per column."""
    conn = connect(path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        schema = {}
        for t in tables:
            cols = []
            for _, name, ctype, *_ in conn.execute(f'PRAGMA table_info("{t}")').fetchall():
                vals = [_short(r[0]) for r in conn.execute(
                    f'SELECT DISTINCT "{name}" FROM "{t}" WHERE "{name}" IS NOT NULL '
                    f'AND typeof("{name}") <> ? LIMIT {samples}', ("blob",))]
                cols.append({"name": name, "type": ctype, "samples": vals})
            schema[t] = cols
        return schema
    finally:
        conn.close()


def format_schema(schema: dict) -> str:
    lines = []
    for table, cols in schema.items():
        lines.append(f"TABLE {quote_name(table)}")
        for c in cols:
            sample = ", ".join(repr(v) for v in c["samples"])
            lines.append(f"  {quote_name(c['name'])} {c['type']}  e.g. {sample}")
    return "\n".join(lines)
