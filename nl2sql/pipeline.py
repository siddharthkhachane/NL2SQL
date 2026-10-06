import time
from functools import lru_cache

from nl2sql import db
from nl2sql.generate import generate_sql


@lru_cache(maxsize=1)
def _schema_text() -> str:
    return db.format_schema(db.get_schema())


def ask(question: str) -> dict:
    """Returns {sql, rows, columns, error, timings}."""
    result = {"sql": None, "columns": [], "rows": [], "error": None, "timings": {}}

    t = time.perf_counter()
    schema_text = _schema_text()
    result["timings"]["schema"] = time.perf_counter() - t

    t = time.perf_counter()
    try:
        result["sql"] = generate_sql(question, schema_text)
    except Exception as e:
        result["error"] = f"generation failed: {e}"
        return result
    finally:
        result["timings"]["generate"] = time.perf_counter() - t

    t = time.perf_counter()
    try:
        result["columns"], result["rows"] = db.execute_safe(result["sql"])
    except Exception as e:
        result["error"] = str(e)
    result["timings"]["execute"] = time.perf_counter() - t
    return result
