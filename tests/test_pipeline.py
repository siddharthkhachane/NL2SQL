from nl2sql import pipeline


def test_ask_runs_generated_sql_and_times_stages(monkeypatch):
    monkeypatch.setattr(pipeline, "generate_sql", lambda q, s: "SELECT COUNT(*) AS n FROM Teams")
    out = pipeline.ask("how many team seasons?")
    assert out["error"] is None
    assert out["columns"] == ["n"] and out["rows"][0][0] > 3000
    assert set(out["timings"]) == {"schema", "generate", "execute"}


def test_ask_blocks_unsafe_generated_sql(monkeypatch):
    monkeypatch.setattr(pipeline, "generate_sql", lambda q, s: "DROP TABLE Teams")
    out = pipeline.ask("anything")
    assert out["rows"] == [] and "only SELECT" in out["error"]


def test_ask_reports_generation_failure(monkeypatch):
    def boom(q, s):
        raise RuntimeError("no key")
    monkeypatch.setattr(pipeline, "generate_sql", boom)
    out = pipeline.ask("anything")
    assert "generation failed" in out["error"] and out["sql"] is None
