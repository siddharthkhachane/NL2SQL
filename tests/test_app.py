from pathlib import Path

from streamlit.testing.v1 import AppTest

from nl2sql import pipeline

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def fake_ask(question, **flags):
    fake_ask.calls.append((question, flags))
    return {"sql": "SELECT 1 AS n", "columns": ["n"], "rows": [(1,)], "error": None,
            "timings": {"schema": 0.01, "generate": 1.5, "execute": 0.02}, "tables": None,
            "assumptions": "treated 'last season' as 2025", "refused": False, "retried": True, "first": None}


fake_ask.calls = []


def test_page_loads_and_shows_saved_eval_results():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["QUESTION", "EVAL"]
    text = " ".join(m.value for m in at.markdown)
    assert "execution accuracy" in text and "By join count" in text
    assert len(at.dataframe) >= 4


def test_question_goes_through_pipeline_ask_and_renders_answer(monkeypatch):
    fake_ask.calls.clear()
    monkeypatch.setattr(pipeline, "ask", fake_ask)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("Who led the league?").run()
    at.button[0].click().run()
    assert not at.exception
    assert fake_ask.calls == [("Who led the league?", {"linking": False, "retry": True,
                                                       "assumptions": True, "gate": True})]
    assert at.code[0].value == "SELECT 1 AS n"
    text = " ".join(m.value for m in at.markdown)
    assert "treated 'last season' as 2025" in text and "generate 1.50s" in text and "retried" in text


def test_refusal_is_shown(monkeypatch):
    def refuse(question, **flags):
        return {"sql": None, "columns": [], "rows": [], "error": None, "timings": {"generate": 0.5},
                "tables": None, "assumptions": None, "refused": True, "retried": False, "first": None}

    monkeypatch.setattr(pipeline, "ask", refuse)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("pitches?").run()
    at.button[0].click().run()
    assert "cannot answer" in " ".join(m.value for m in at.markdown) and len(at.code) == 0
