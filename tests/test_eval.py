import json

import pytest

from eval import run_eval as ev
from nl2sql import databases, db

QUESTIONS = ev.load_questions()


def test_question_set_shape():
    assert len(QUESTIONS) == 43
    assert all(set(q) >= {"id", "question", "gold_sql", "join_count", "trap", "split"} for q in QUESTIONS)
    assert len({q["id"] for q in QUESTIONS}) == 43
    assert sum(q["gold_sql"] is None for q in QUESTIONS) == 5
    assert {q["trap"] for q in QUESTIONS} >= {
        "stint", "franchise", "inconsistent_columns", "duplicate_names", "time", "unanswerable", "wide_table"}
    assert {ev.bucket(q["join_count"]) for q in QUESTIONS if q["gold_sql"]} == {"0", "1", "2", "3+"}
    lahman = [q for q in QUESTIONS if ev.qdb(q) == "lahman"]
    assert len(lahman) == 25
    assert sum(q["split"] == "heldout" for q in lahman) == 7
    assert sum(q["split"] == "heldout_new" for q in lahman) == 5
    for name in ("sakila", "northwind"):
        qs = [q for q in QUESTIONS if ev.qdb(q) == name]
        assert len(qs) == 9 and sum(q["gold_sql"] is None for q in qs) == 1
        assert 2 <= sum(q["split"] == "heldout" for q in qs) <= 4


def _gold_params():
    return [q for q in QUESTIONS if q["gold_sql"]]


@pytest.mark.parametrize("q", _gold_params(), ids=lambda q: q["id"])
def test_gold_returns_rows(q):
    path = databases.path(ev.qdb(q))
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    assert len(db.execute_safe(q["gold_sql"], limit=100000, path=path)[1]) >= 1


def test_results_match_order_rules():
    a, b = [(1, "x"), (2, "y")], [(2, "y"), (1, "x")]
    assert ev.results_match(a, b, "SELECT a, b FROM t")
    assert not ev.results_match(a, b, "SELECT a, b FROM t ORDER BY a")
    assert not ev.results_match([(1,)], [(2,)], "SELECT a FROM t")
    assert ev.results_match([(1.00001,)], [(1.0,)], "SELECT a FROM t")


def test_exact_match_is_stricter_than_execution_match():
    q = next(q for q in QUESTIONS if q["id"] == "q02")
    out = {"sql": "SELECT COUNT(playerID) FROM People WHERE birthCountry = 'Japan'", "rows": [(84,)], "error": None}
    rec = ev.score(q, out)
    assert rec["exec_match"] and not rec["exact_match"]
    out["sql"] = q["gold_sql"] + ";"
    assert ev.score(q, out)["exact_match"]


def test_score_unanswerable_and_failure_tag():
    q = next(q for q in QUESTIONS if q["trap"] == "unanswerable")
    assert ev.score(q, {"sql": "I cannot answer", "error": "only SELECT statements are allowed"})["exec_match"]
    assert not ev.score(q, {"sql": "SELECT 1", "rows": [(1,)], "error": None})["exec_match"]
    q6 = next(q for q in QUESTIONS if q["id"] == "q06")
    wrong = {"sql": "SELECT HR FROM Batting b JOIN People p ON b.playerID = p.playerID WHERE p.nameLast = 'McGwire' "
                    "AND yearID = 1997 LIMIT 1", "rows": [(34,)], "error": None}
    rec = ev.score(q6, wrong)
    assert not rec["exec_match"] and rec["failure"] == "stint"
    assert ev.score(q6, {"sql": "SELEC", "rows": [], "error": "near SELEC"})["failure"] == "syntax"


def test_run_summarizes_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "RESULTS_DIR", tmp_path)
    gold = {q["question"]: q["gold_sql"] for q in QUESTIONS}

    def oracle(q):
        sql = gold[q["question"]]
        if sql is None:
            return {"sql": None, "rows": [], "error": "refused", "timings": {}}
        rows = db.execute_safe(sql, limit=100000, path=databases.path(ev.qdb(q)))[1]
        return {"sql": sql, "rows": rows, "error": None, "timings": {}}

    res = ev.run(oracle, label="oracle")
    assert res["summary"]["overall"] == {"n": 43, "exec_acc": 1.0, "exact_match": 0.884}
    assert set(res["summary"]["by_join_bucket"]) == {"0", "1", "2", "3+", "n/a"}
    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["label"] == "oracle" and len(saved["records"]) == 43


def test_generation_failure_is_not_tagged_as_syntax():
    q6 = next(q for q in QUESTIONS if q["id"] == "q06")
    rec = ev.score(q6, {"sql": None, "rows": [], "error": "generation failed: 429 rate limit"})
    assert rec["failure"] == "other"
