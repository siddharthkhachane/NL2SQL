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

## Phase 3
- Temperature was set to 0 in `generate.py` and the baseline re-run (`baseline_t0`) so baseline vs linking is comparable. Scores matched the Phase 2 run (15/20).
- The first linking run scored 65%, but two of its failures (q12, q16) were OpenAI 429 rate-limit errors (30k TPM) tagged as `syntax`. Detected by reading the error text of the failed records. Fixes: `max_retries=8` on the client, and generation errors are now tagged `other`. The run was repeated; the 429 run is kept in `eval/results/20261005_210035.json` but is not valid.
- Join inference works without hard-coding the dimension tables: the uniqueness check found People (playerID), Teams (teamID+yearID), TeamsFranchises, Schools, Parks. Only the `HomeGames` alias map is explicit.
- Retrieval recall is poor on its own: top-5 contains all gold tables for 6/17 answerable questions (0.353). Adding dimension-table neighbors lifts it to 14/17 (0.824). 3+ join questions: 0/2 either way (CollegePlaying / Schools are not retrieved).
- The one question that flipped from correct to wrong with linking is q12: retrieval missed `AllstarFull` ("All-Stars" does not look like the table name to a MiniLM embedding), so the model used `Appearances` instead.
- The baseline's q12 pass was partly luck: it filtered `b.HR >= 40` on single rows rather than summing stints. Same data, so no change in score, but the pass is not evidence the trap is handled.
- Average per-question latency (link/schema + generate): baseline 10.5 s, linking 4.8 s. Baseline timings include 429 back-off waits, so do not read this as a clean speedup.

### Baseline vs linking (execution accuracy, 20 questions)
| bucket | baseline | linking |
|---|---|---|
| overall | 0.75 | 0.70 |
| 0 joins (n=5) | 1.00 | 1.00 |
| 1 join (n=6) | 0.83 | 0.83 |
| 2 joins (n=4) | 0.75 | 0.50 |
| 3+ joins (n=2) | 1.00 | 1.00 |
| unanswerable (n=3) | 0.00 | 0.00 |

Retrieval recall (top-5 / with neighbors): 0 joins 1.00/1.00, 1 join 0.17/1.00, 2 joins 0.00/0.75, 3+ joins 0.00/0.00, overall 0.35/0.82.

Finding: on a 27-table schema that fits in the prompt (about 14k characters), linking did not improve accuracy. The difference is a single question (5 points), which is within noise for a 20-question eval. The retrieval step costs recall that the full schema never loses.
