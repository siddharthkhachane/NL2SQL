import pytest

from nl2sql import databases, db, pipeline, router
from nl2sql.semantic import with_glossary

needs_all = pytest.mark.skipif(len(databases.available()) < 3, reason="needs lahman, sakila and northwind files")


def test_unknown_database_name_is_rejected():
    with pytest.raises(ValueError, match="unknown database"):
        databases.path("nope")


@pytest.mark.skipif("sakila" not in databases.available(), reason="sakila file not present")
def test_sql_runs_against_the_selected_database(monkeypatch):
    monkeypatch.setattr(pipeline, "generate_sql", lambda q, s: "SELECT COUNT(*) FROM film")
    out = pipeline.ask("how many films?", database="sakila")
    assert out["database"] == "sakila" and out["rows"] == [(1000,)]
    # the same SQL against the default database has no such table
    default = pipeline.ask("how many films?")
    assert default["database"] == "lahman" and "no such table" in default["error"]


@pytest.mark.skipif("sakila" not in databases.available(), reason="sakila file not present")
def test_prompt_contains_only_the_selected_schema(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "generate_sql", lambda q, s: seen.append(s) or "SELECT 1")
    pipeline.ask("q", database="sakila", semantic=True)
    assert "TABLE film_actor" in seen[0] and "TABLE Batting" not in seen[0]
    assert "NOTES ABOUT THIS DATA" not in seen[0]  # the glossary is Lahman-specific


def test_glossary_is_only_for_databases_that_have_one():
    assert with_glossary("S", "sakila") == "S"
    assert with_glossary("S", "lahman").endswith("\n\nS") and "Stints" in with_glossary("S", "lahman")


@pytest.mark.skipif("northwind" not in databases.available(), reason="northwind file not present")
def test_northwind_schema_text_is_clean():
    text = databases.schema_text("northwind")
    assert 'TABLE "Order Details"' in text
    assert "sqlite_sequence" not in text and "xff" not in text and "JFIF" not in text


def test_routed_ask_uses_the_routers_choice(monkeypatch):
    class FakeRouter:
        def route(self, question):
            return "sakila", {"lahman": 0.1, "sakila": 0.4, "northwind": 0.2}

    monkeypatch.setattr(router, "get_router", lambda: FakeRouter())
    monkeypatch.setattr(pipeline, "generate_sql", lambda q, s: "SELECT COUNT(*) FROM actor")
    out = pipeline.ask("q", route=True)
    assert out["database"] == "sakila" and out["route_scores"]["sakila"] == 0.4 and "route" in out["timings"]
    if "sakila" in databases.available():
        assert out["rows"] == [(200,)]


@needs_all
@pytest.mark.parametrize("question, expected", [
    ("How many home runs did Babe Ruth hit in 1927?", "lahman"),
    ("Which team won the most games in 2001?", "lahman"),
    ("How many films are rated PG-13?", "sakila"),
    ("How many rental customers live in Canada?", "sakila"),
    ("How many products are discontinued?", "northwind"),
    ("What was the total revenue in 2016, after discounts?", "northwind"),
])
def test_router_picks_the_right_database_for_clear_questions(question, expected):
    name, scores = router.get_router().route(question)
    assert name == expected, scores
    assert set(scores) == {"lahman", "sakila", "northwind"}


def test_execute_safe_still_blocks_writes_on_other_databases():
    if "sakila" not in databases.available():
        pytest.skip("sakila file not present")
    with pytest.raises(db.UnsafeSQL):
        db.execute_safe("DELETE FROM film", path=databases.path("sakila"))
