import sqlite3

import pytest

from nl2sql import db, linking, pipeline


@pytest.fixture
def small_db(tmp_path):
    path = tmp_path / "s.sqlite"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE People (playerID TEXT, nameFirst TEXT);
        CREATE TABLE Teams (yearID INTEGER, teamID TEXT, lgID TEXT, name TEXT);
        CREATE TABLE Batting (playerID TEXT, yearID INTEGER, stint INTEGER, teamID TEXT, lgID TEXT, HR INTEGER);
        CREATE TABLE HomeGames (yearkey INTEGER, leaguekey TEXT, teamkey TEXT, parkkey TEXT, attendance INTEGER);
        CREATE TABLE Parks (parkkey TEXT, parkname TEXT);
        CREATE TABLE Other (yearID INTEGER, lgID TEXT, note TEXT);
        INSERT INTO People VALUES ('a1','Al'), ('b1','Bo');
        INSERT INTO Teams VALUES (2000,'BOS','AL','Red Sox'), (2001,'BOS','AL','Red Sox'), (2000,'NYA','AL','Yankees');
        INSERT INTO Batting VALUES ('a1',2000,1,'BOS','AL',5), ('a1',2000,2,'NYA','AL',3), ('b1',2001,1,'BOS','AL',1), ('b1',2000,1,'BOS','AL',2);
        INSERT INTO HomeGames VALUES (2000,'AL','BOS','P1',10), (2001,'AL','BOS','P1',20);
        INSERT INTO Parks VALUES ('P1','Fenway');
        INSERT INTO Other VALUES (2000,'AL','x');
    """)
    c.commit()
    c.close()
    return path


def test_key_detection_and_alias():
    assert linking.is_key("playerID") and linking.is_key("parkkey") and linking.is_key("yearkey")
    assert not linking.is_key("HR") and not linking.is_key("ID")
    assert linking.canon("teamkey") == "teamID" and linking.canon("playerID") == "playerID"


def test_inferred_joins_use_alias_and_skip_weak_only_pairs(small_db):
    schema = db.get_schema(small_db)
    joins = linking.inferred_joins(schema, ["Batting", "People", "HomeGames", "Parks", "Other"])
    assert "Batting.playerID = People.playerID" in joins
    assert any("HomeGames.teamkey" in j and "Batting.teamID" in j for j in joins)  # alias map
    assert "HomeGames.parkkey = Parks.parkkey" in joins
    assert not any("Other" in j for j in joins)  # shares only yearID/lgID


def test_dimension_tables_found_by_uniqueness(small_db):
    dims = linking.dimension_tables(db.get_schema(small_db), small_db)
    assert dims == {"playerID": "People", "teamID": "Teams", "parkkey": "Parks"}


def test_expand_adds_dimension_tables_but_keeps_original_set(small_db):
    schema = db.get_schema(small_db)
    linker = linking.Linker.__new__(linking.Linker)
    linker.schema, linker.dims = schema, linking.dimension_tables(schema, small_db)
    assert linker.expand(["Batting"]) == ["Batting", "People", "Teams"]
    assert linker.expand(["HomeGames"]) == ["HomeGames", "Teams", "Parks"]
    assert linker.expand(["Other"]) == ["Other"]


@pytest.mark.skipif(not db.DB_PATH.exists(), reason="data/lahman.sqlite not present")
def test_retrieval_and_link_on_real_schema():
    linker = linking.get_linker()
    assert "Salaries" in linker.retrieve("What was the highest salary last season?")
    out = linker.link("How many home runs did Mark McGwire hit in 1997?")
    assert {"Batting", "People"} <= set(out["tables"]) and len(out["tables"]) < 27
    assert "INFERRED JOINS" in out["schema_text"] and "TABLE Batting" in out["schema_text"]
    assert "TABLE Parks" not in out["schema_text"]


def test_ask_with_linking_uses_subset_schema(monkeypatch):
    seen = {}

    class FakeLinker:
        def link(self, question):
            return {"retrieved": ["Teams"], "tables": ["Teams", "People"], "schema_text": "SUBSET",
                    "details": [{"table": "Teams", "how": "retrieved", "score": 0.5, "match": "(table)"}],
                    "joins": ["Teams.teamID = People.playerID"]}

    monkeypatch.setattr(linking, "get_linker", lambda *a: FakeLinker())
    monkeypatch.setattr(pipeline, "generate_sql", lambda q, s: seen.setdefault("schema", s) and "SELECT 1")
    out = pipeline.ask("q", linking=True)
    assert seen["schema"] == "SUBSET" and out["tables"] == ["Teams", "People"] and "link" in out["timings"]


def test_tables_in_scans_from_and_join():
    sql = "SELECT * FROM Batting b JOIN People p ON b.playerID = p.playerID WHERE x IN (SELECT y FROM Teams)"
    assert db.tables_in(sql) == {"batting", "people", "teams"}
    assert db.tables_in(None) == set()


@pytest.mark.skipif(not db.DB_PATH.exists(), reason="data/lahman.sqlite not present")
def test_link_reports_scores_matches_and_added_neighbors():
    out = linking.get_linker().link("How many home runs did Mark McGwire hit in 1997?")
    retrieved = [d for d in out["details"] if d["how"] == "retrieved"]
    added = [d for d in out["details"] if d["how"].startswith("added")]
    assert len(retrieved) == 5 and all(0 < d["score"] <= 1 and d["match"] for d in retrieved)
    assert [d["score"] for d in retrieved] == sorted((d["score"] for d in retrieved), reverse=True)
    assert {d["table"] for d in added} == set(out["tables"]) - set(out["retrieved"])
    assert any("Batting.playerID = People.playerID" == j for j in out["joins"]) or out["joins"]
