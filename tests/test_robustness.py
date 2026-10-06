import json

from eval import run_eval as ev
from nl2sql import generate, pipeline

GOOD = "SELECT COUNT(*) AS n FROM Teams"
BAD = "SELECT nope FROM Teams"
EMPTY = "SELECT * FROM Teams WHERE yearID = 1"


def scripted(monkeypatch, replies, calls=None):
    """Make generate_sql / generate_structured return successive replies; record the feedback they get."""
    it = iter(replies)

    def gen_sql(q, s, model=None, feedback=None):
        if calls is not None:
            calls.append(feedback)
        return next(it)

    def gen_struct(q, s, assumptions, gate, model=None, feedback=None):
        if calls is not None:
            calls.append(feedback)
        return next(it)

    monkeypatch.setattr(pipeline, "generate_sql", gen_sql)
    monkeypatch.setattr(pipeline, "generate_structured", gen_struct)


def test_retry_fixes_sql_error_and_passes_the_error_back(monkeypatch):
    calls = []
    scripted(monkeypatch, [BAD, GOOD], calls)
    out = pipeline.ask("q", retry=True)
    assert out["error"] is None and out["rows"][0][0] > 3000
    assert out["retried"] and out["first"]["error"] and out["sql"] == GOOD
    assert calls[0] is None and BAD in calls[1] and "no such column" in calls[1]
    assert "retry" in out["timings"]


def test_no_retry_when_disabled_or_when_first_attempt_works(monkeypatch):
    scripted(monkeypatch, [BAD])
    out = pipeline.ask("q", retry=False)
    assert out["error"] and not out["retried"]
    scripted(monkeypatch, [GOOD, GOOD])
    out = pipeline.ask("q", retry=True)
    assert not out["retried"] and out["first"] is None


def test_retry_on_empty_result(monkeypatch):
    calls = []
    scripted(monkeypatch, [EMPTY, GOOD], calls)
    out = pipeline.ask("q", retry=True)
    assert out["retried"] and out["rows"] and "no rows" in calls[1]


def test_retry_happens_at_most_once(monkeypatch):
    calls = []
    scripted(monkeypatch, [BAD, BAD, GOOD], calls)
    out = pipeline.ask("q", retry=True)
    assert len(calls) == 2 and out["error"]


def test_no_retry_for_non_select_refusal_text(monkeypatch):
    calls = []
    scripted(monkeypatch, ["I cannot answer that", GOOD], calls)
    out = pipeline.ask("q", retry=True)
    assert len(calls) == 1 and not out["retried"]


def test_gate_refuses_without_executing(monkeypatch):
    scripted(monkeypatch, [{"sql": "", "answerable": False, "assumptions": "no pitch data"}])
    monkeypatch.setattr(pipeline.db, "execute_safe", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    out = pipeline.ask("pitches?", gate=True)
    assert out["refused"] and out["sql"] is None and out["assumptions"] == "no pitch data"


def test_gate_off_does_not_refuse(monkeypatch):
    scripted(monkeypatch, [{"sql": GOOD, "answerable": False}])
    out = pipeline.ask("q", assumptions=True)
    assert not out["refused"] and out["rows"]


def test_assumptions_are_returned(monkeypatch):
    scripted(monkeypatch, [{"sql": GOOD, "assumptions": "last season = 2025"}])
    assert pipeline.ask("q", assumptions=True)["assumptions"] == "last season = 2025"


def test_structured_prompt_depends_on_flags(monkeypatch):
    seen = []
    monkeypatch.setattr(generate, "_complete", lambda prompt, model=None, json_mode=False:
                        seen.append((prompt, json_mode)) or json.dumps({"sql": "```sql\nSELECT 1\n```", "x": 1}))
    out = generate.generate_structured("q", "SCHEMA", assumptions=True, gate=False)
    assert out["sql"] == "SELECT 1" and seen[0][1] is True
    assert "assumptions:" in seen[0][0] and "answerable:" not in seen[0][0] and "2025" in seen[0][0]
    generate.generate_structured("q", "SCHEMA", assumptions=False, gate=True)
    assert "answerable:" in seen[1][0] and "assumptions:" not in seen[1][0]


def test_structured_falls_back_when_reply_is_not_json(monkeypatch):
    monkeypatch.setattr(generate, "_complete", lambda *a, **k: "```sql\nSELECT 2\n```")
    assert generate.generate_structured("q", "S", True, True)["sql"] == "SELECT 2"


def test_retry_feedback_text():
    assert "boom" in generate.retry_feedback("SELECT 1", "boom")
    assert "no rows" in generate.retry_feedback("SELECT 1", None)


def test_eval_scores_refusal_and_first_attempt():
    unans = next(q for q in ev.load_questions() if q["trap"] == "unanswerable")
    assert ev.score(unans, {"sql": None, "refused": True, "rows": [], "error": None})["exec_match"]
    q = next(q for q in ev.load_questions() if q["id"] == "q02")
    out = {"sql": q["gold_sql"], "rows": [(84,)], "error": None, "retried": True,
           "first": {"sql": BAD, "rows": [], "error": "no such column"}}
    rec = ev.score(q, out)
    assert rec["exec_match"] and not rec["first_attempt_match"] and rec["retried"]
    wrong = ev.score(q, {"sql": None, "refused": True, "rows": [], "error": None})
    assert not wrong["exec_match"] and wrong["failure"] == "other"
    s = ev.summarize([rec, wrong])["answerable_only"]
    assert s["retry_rate"] == 0.5 and s["first_attempt_acc"] == 0.0 and s["final_acc"] == 0.5
    assert s["false_refusals"] == 1
