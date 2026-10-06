# Notes

Surprises and failures, in order found.

## Phase 0
- `lahman.sqlite` was in the repo root, outside `data/`, so the original `data/*.sqlite` ignore rule would not have covered it. Moved it to `data/` and widened `.gitignore` to `*.sqlite`, `*.db`, `*.csv`, `*.zip`, `*.parquet`.
- First pytest run failed with `ModuleNotFoundError: nl2sql`: the bare uv project has no build config. Fixed with `pythonpath = ["."]` under `[tool.pytest.ini_options]`.

## Phase 1
- Provider is OpenAI, not Anthropic (changed after the key was supplied). Default model `gpt-4o` is a placeholder; override with `NL2SQL_MODEL`.
- Executor also allows `WITH`; a `WITH ... DELETE` is stopped by the SQLite authorizer and the read-only connection (tested).

## Phase 2
- `docs/readme2025.txt` was not available. Gold SQL was written from the schema and checked against the data instead.
- SQLite column names are case-insensitive, and `HAVING h >= 40` with alias `h` resolved to the `H` (hits) column instead of the alias. Found while exploring; gold SQL uses `HAVING SUM(HR) >= 40`.
- `Teams.attendance` for BOS 2019 is 2,924,627 but the sum of `HomeGames.attendance` is 2,915,502 (it includes 2 London games at `LON01`). q05 gold uses `HomeGames`; a model answering from `Teams` gets a different, defensible number.
- 1997 is a good stint case: McGwire has 58 HR across two stints (OAK 34, SLN 24), while the largest single row is Griffey's 56.
- Baseline (gpt-4o, full schema): 15/20 execution accuracy, exact-match 1/20. The 3 unanswerable questions all fail because the baseline has no refusal path; it wrote SQL for each (e.g. it invented a "RISP" average from `R > 0`).
- q07 (most HR in 1997) failed: model took the largest single `Batting` row, not the sum over stints.
- q13 (Dodgers franchise players) failed by one: the model used `Appearances` (2002) instead of `Batting` (2003). Both are reasonable; the failure tag says `schema_linking`, which is a heuristic label, not proof.
- q10 (last season) passed only because the leader (Raleigh, 60) was a single-stint season; the model used `MAX(yearID)` without saying so.
- Failure tags are heuristic (trap + simple SQL features), so treat `other`/`schema_linking` as a prompt to read the SQL.
