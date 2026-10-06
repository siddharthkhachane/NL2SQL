import time
from functools import lru_cache

from nl2sql import db
from nl2sql.generate import generate_sql


@lru_cache(maxsize=1)
def _schema_text() -> str:
    return db.format_schema(db.get_schema())


def ask(question: str, linking: bool = False) -> dict:
    """Returns {sql, columns, rows, error, timings, tables}. `tables` is set only when linking is on."""
    result = {"sql": None, "columns": [], "rows": [], "error": None, "timings": {}, "tables": None}

    t = time.perf_counter()
    if linking:
        from nl2sql.linking import get_linker

        linked = get_linker().link(question)
        schema_text = linked["schema_text"]
        result["tables"] = linked["tables"]
        result["retrieved"] = linked["retrieved"]
    else:
        schema_text = _schema_text()
    result["timings"]["link" if linking else "schema"] = time.perf_counter() - t

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
