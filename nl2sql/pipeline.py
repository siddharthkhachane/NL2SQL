import time
from functools import lru_cache

from nl2sql import db
from nl2sql.generate import generate_sql, generate_structured, retry_feedback
from nl2sql.semantic import with_glossary


@lru_cache(maxsize=1)
def _schema_text() -> str:
    return db.format_schema(db.get_schema())


def _execute(sql: str):
    try:
        columns, rows = db.execute_safe(sql)
        return columns, rows, None
    except Exception as e:
        return [], [], str(e)


def _is_refusal_error(error: str | None) -> bool:
    return bool(error) and ("only SELECT" in error or "empty query" in error)


def ask(question: str, linking: bool = False, retry: bool = False, assumptions: bool = False,
        gate: bool = False, semantic: bool = False) -> dict:
    """Returns {sql, columns, rows, error, timings, tables, assumptions, refused, retried, first}.

    retry: on an execution error or empty result, regenerate once with the problem as feedback.
    assumptions: the model also returns one sentence on how it resolved ambiguity.
    gate: the model may refuse questions the schema cannot answer (sql=None, refused=True).
    semantic: prepend a glossary of how the data is modeled (stints, franchises) to the schema.
    """
    result = {"sql": None, "columns": [], "rows": [], "error": None, "timings": {}, "tables": None,
              "assumptions": None, "refused": False, "retried": False, "first": None}

    t = time.perf_counter()
    if linking:
        from nl2sql.linking import get_linker

        linked = get_linker().link(question)
        schema_text = linked["schema_text"]
        result["tables"], result["retrieved"] = linked["tables"], linked["retrieved"]
    else:
        schema_text = _schema_text()
    result["timings"]["link" if linking else "schema"] = time.perf_counter() - t
    if semantic:
        schema_text = with_glossary(schema_text)

    structured = assumptions or gate

    def generate(feedback=None):
        if structured:
            return generate_structured(question, schema_text, assumptions, gate, feedback=feedback)
        if feedback:
            return {"sql": generate_sql(question, schema_text, feedback=feedback)}
        return {"sql": generate_sql(question, schema_text)}

    t = time.perf_counter()
    try:
        gen = generate()
    except Exception as e:
        result["error"] = f"generation failed: {e}"
        return result
    finally:
        result["timings"]["generate"] = time.perf_counter() - t

    result["assumptions"] = gen.get("assumptions")
    if gate and (gen.get("answerable") is False or not gen.get("sql")):
        result["refused"] = True
        return result
    result["sql"] = gen["sql"]

    t = time.perf_counter()
    result["columns"], result["rows"], result["error"] = _execute(result["sql"])
    result["timings"]["execute"] = time.perf_counter() - t

    needs_retry = (result["error"] and not _is_refusal_error(result["error"])) or \
                  (not result["error"] and not result["rows"])
    if retry and needs_retry:
        result["retried"] = True
        result["first"] = {"sql": result["sql"], "rows": result["rows"], "error": result["error"]}
        t = time.perf_counter()
        try:
            second = generate(retry_feedback(result["sql"], result["error"]))
            if second.get("sql"):
                result["sql"] = second["sql"]
                result["assumptions"] = second.get("assumptions") or result["assumptions"]
                result["columns"], result["rows"], result["error"] = _execute(result["sql"])
        except Exception as e:
            result["error"] = f"generation failed: {e}"
        result["timings"]["retry"] = time.perf_counter() - t
    return result
