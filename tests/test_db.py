import sqlite3

import pytest

from nl2sql import db
from nl2sql.generate import strip_fences


@pytest.fixture
def dbfile(tmp_path):
    path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE T (id INTEGER, name TEXT)")
    conn.executemany("INSERT INTO T VALUES (?, ?)", [(i, f"n{i}") for i in range(500)])
    conn.commit()
    conn.close()
    return path


def test_accepts_plain_select(dbfile):
    cols, rows = db.execute_safe("SELECT id, name FROM T WHERE id = 3", path=dbfile)
    assert cols == ["id", "name"] and rows == [(3, "n3")]


def test_accepts_trailing_semicolon_and_semicolon_in_string(dbfile):
    assert db.execute_safe("SELECT 1;", path=dbfile)[1] == [(1,)]
    assert db.execute_safe("SELECT 'a;b'", path=dbfile)[1] == [("a;b",)]


@pytest.mark.parametrize("sql", [
    "DROP TABLE T",
    "INSERT INTO T VALUES (1, 'x')",
    "UPDATE T SET name = 'x'",
    "DELETE FROM T",
    "SELECT 1; DROP TABLE T",
    "SELECT 1; SELECT 2",
    "SELECT 1 -- ; DROP TABLE T",
    "SELECT 1 /* x */",
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE 'x.db' AS x",
    "",
])
def test_rejects_unsafe(dbfile, sql):
    with pytest.raises(db.UnsafeSQL):
        db.execute_safe(sql, path=dbfile)


def test_connection_is_read_only(dbfile):
    conn = db.connect(dbfile)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DROP TABLE T")
    conn.close()


def test_with_cannot_write(dbfile):
    with pytest.raises(sqlite3.Error):
        db.execute_safe("WITH x AS (SELECT 1) DELETE FROM T", path=dbfile)
    assert db.execute_safe("SELECT COUNT(*) FROM T", path=dbfile)[1] == [(500,)]


def test_row_limit(dbfile):
    assert len(db.execute_safe("SELECT * FROM T", path=dbfile)[1]) == 100
    assert len(db.execute_safe("SELECT * FROM T", limit=7, path=dbfile)[1]) == 7


def test_timeout(dbfile):
    slow = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c"
    with pytest.raises(sqlite3.OperationalError):
        db.execute_safe(slow, timeout=0.2, path=dbfile)


def test_schema_samples(dbfile):
    schema = db.get_schema(dbfile)
    assert [c["name"] for c in schema["T"]] == ["id", "name"]
    assert len(schema["T"][1]["samples"]) == 3
    assert "TABLE T" in db.format_schema(schema)


def test_strip_fences():
    assert strip_fences("```sql\nSELECT 1\n```") == "SELECT 1"
    assert strip_fences("SELECT 1") == "SELECT 1"
