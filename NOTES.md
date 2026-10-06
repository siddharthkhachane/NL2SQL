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
- Memorization: with linking on, q16 and q17 (3+ joins) were answered correctly using tables that were not in the prompt (`CollegePlaying`, `Salaries`), including the guess `schoolID = 'usc'`. Detected by comparing `tables` with the tables in `pred_sql`. gpt-4o appears to know the public Lahman schema, so (a) linking cannot restrict the model, because the executor still sees all 27 tables, and (b) the 3+ join accuracy of 1.0 despite 0/2 retrieval recall is not evidence of working linking. A fair test would rename tables/columns or use a database the model has not seen.

## Phase 4
All runs use the full-schema pipeline (no linking), gpt-4o, temperature 0. Each run is cumulative.

| run | exec acc (20) | answerable acc (17) | first-attempt acc | retry rate | unanswerable refused | false refusals |
|---|---|---|---|---|---|---|
| baseline_t0 | 0.75 | 0.88 | 0.88 | - | 0/3 | - |
| + retry | 0.75 | 0.88 | 0.88 | 0.00 | 0/3 | 0 |
| + retry + assumptions | 0.75 | 0.88 | 0.88 | 0.00 | 0/3 | 0 |
| + retry + assumptions + gate | 0.85 | 0.82 | 0.82 | 0.00 | 3/3 | 1 |

- Retry never fired: on all 17 answerable questions the baseline SQL ran without error and returned rows, so there was nothing to retry. Before/after is identical (0.88 / 0.88). The retry path is covered by unit tests with scripted model replies, not by the eval. The remaining errors are wrong-but-valid SQL (stint, Appearances vs Batting), which neither an error nor an empty result can detect.
- Assumptions: useful on the time questions (q03: "Salaries ends in 2016"; q10: "last season = 2025"; q14: "most recent salary season is 2016"). Weak elsewhere: q07 and q12 (the stint failures/luck cases) say "none", so the model does not notice stints; q08's sentence is vacuous; q05 says it used `Teams` while the passing SQL used `HomeGames`, so the sentence is not a reliable description of the query.
- Gate: refused 3/3 unanswerable questions with sensible reasons (no pitch data, no play-by-play, no 2026 data). It also refused q03 ("highest salary last season") because `Salaries` ends in 2016 and "last season" would be 2025. The gold query resolves it to 2016, so this counts as a false refusal; it is arguably a reasonable flag. Net accuracy on all 20 rose from 0.75 to 0.85, but answerable accuracy fell from 0.88 to 0.82. The gate trades one answerable question for three unanswerable ones.
- Heldout (7 questions, never used for tuning): 0.57 before the gate, 0.71 after.
- Each eval run takes 4-5 minutes because of the 30k tokens-per-minute OpenAI limit with ~4k-token prompts and `max_retries=8` back-off.

## Phase 5
- The first CSS override (`[class*="st-"] { font-family: ... }`) replaced the Material icon font, so the sidebar toggle rendered as the text "double_arrow_right". Found by screenshot; icon elements are now excluded from the font rule.
- Streamlit headings ignore the body font and the text input's fill sits on a wrapper div, not the `<input>`; both needed their own selectors (found by inspecting computed styles in the browser).
- Running the real pipeline from the page on the 1997 home run question reproduced the known stint failure (Griffey, 56 instead of McGwire, 58) with assumptions "none".

## Improvements branch, step 1: semantic layer
Added `nl2sql/semantic.py`: a short glossary (stints, franchises) prepended to the schema when `semantic=True` / `--semantic`. Written from the data's structure, not from eval questions. I had already seen the baseline failures on the original held-out questions (q07, q13), so those are not clean test data; 5 new held-out questions (`heldout_new`, q21-q25: 2 stint, 2 franchise, 1 control) were written and verified before the glossary existed. A first draft of the glossary used the Braves as its franchise example, which mirrors q23; caught on review and changed to the Athletics, who appear in no question.

Same flags (retry + assumptions + gate), 25 questions, temperature 0:

| split | before | with glossary |
|---|---|---|
| all (25) | 0.80 | 0.88 |
| dev (13) | 0.85 | 0.85 |
| heldout (7) | 0.71 | 0.86 |
| heldout_new (5) | 0.80 | 1.00 |
| stint questions (6) | 0.67 | 1.00 |
| franchise questions (5) | 0.80 | 0.80 |

- Only two questions flipped, both "who led in a stat" (q07 most HR in 1997, q21 most stolen bases in 2011): the model now sums per player before ranking. No question got worse.
- The franchise entry shows no measured effect. gpt-4o already handled q23 and q24 (specific franchise, join to TeamsFranchises) without it, so those two questions did not discriminate. The remaining franchise failure, q13, is the Appearances-vs-Batting choice, which the glossary does not address.
- Aggregate-count stint questions (q06, q22) passed with and without the glossary; the model already used SUM when asked for a total. The gap is in ranking, not totals.
- Remaining failures: q03 and q14 are false refusals by the gate ("Salaries ends in 2016, so there is no last season"), even though q14 asks for "the most recent season with salary data". The gate is over-refusing time questions; not touched here.
- Two flipped questions out of 25, one run each: this is suggestive, not statistically strong.

## Improvements branch, step 2: UI transparency
- `Linker.rank()` now returns (table, score, best-matching column) and `link()` returns per-table details and the join list; `ask()` passes them through as `link_details` and `joins`. The page shows them, flags SQL that reads tables that were not in the prompt, and keeps the last result in session state.
- Running the USC question with linking on showed the memorization case directly: the page flagged `collegeplaying` as used but not sent. The inferred-join list was 19 lines for 7 tables (every pair among Batting/Fielding/Appearances/BattingPost/Pitching/Teams/People shares keys), so it is collapsed by default. This noise also goes to the model in the linked prompt.
- Changing a sidebar option used to wipe the result, because it was only drawn on the run where Run was clicked. Fixed with `st.session_state`.
- A long-running `streamlit run` keeps imported modules (`nl2sql.pipeline`) in memory; only `app.py` reloads. After the `semantic` argument was added, the old server raised `TypeError: ask() got an unexpected keyword argument 'semantic'` until restarted. Restart the server after changing anything under `nl2sql/`.
- Writing source files through shell heredocs mangled backslashes twice (`\b` in a regex became a backspace character, `\n` in a string became a real newline). Both were caught by tests failing at collection; fixed by editing the files directly, and all `.py` files were scanned for control characters afterwards.

## Improvements branch, step 3: more databases and a router
Added Sakila (`sakila_master.db`, 16 tables, declared FKs) and Northwind (`northwind.db`, an enlarged variant: 609,283 order lines vs about 2,155 in the classic one, dates shifted to 2012-2023), plus `nl2sql/databases.py` (registry), `nl2sql/router.py` and a `database` / `route` option on `ask()`. 18 gold questions (9 per database, each with 1 unanswerable); gold results were shown and checked row by row. No database-specific hints are given for the new databases (the glossary is Lahman-only).

- Router: embeds every table/column description of every database and scores a database by the mean of its 3 best matches to the question. No tuning. Routing accuracy 42/43 (97.7%) in the eval.
- Found while building: Northwind's `Categories.Picture` put raw JPEG bytes into the schema text (fixed: blob columns are skipped), long descriptions bloated the Sakila schema (values cut at 60 chars), `sqlite_sequence` leaked in as a table (excluded), and tables with spaces (`Order Details`) are now printed quoted.
- Gold-set bugs caught before running: n04 ("supplier with the most products") had a tie (two suppliers with 5), so `LIMIT 1` was arbitrary; replaced. s07 ("how many customers live in Canada?") is answerable in both Sakila and Northwind, so no router can be right; reworded to "rental customers". These are the cross-database ambiguity cases a router cannot resolve from the text alone.
- The model prompt no longer says "Lahman baseball database" (neutral wording for all databases), so the Lahman numbers moved slightly: 0.92 vs 0.88 on the same 25 questions (q14 stopped being refused). One question, one run: not a real effect, but it means the earlier Lahman numbers are not strictly comparable.

Runs (retry + assumptions + gate + glossary, 43 questions, temperature 0):

| | database given | router picks |
|---|---|---|
| all (43) | 0.953 | 0.930 |
| lahman (25) | 0.920 | 0.920 |
| sakila (9) | 1.000 | 0.889 |
| northwind (9) | 1.000 | 1.000 |
| unanswerable refused | 5/5 | 5/5 |
| routing accuracy | - | 0.977 |

- Sakila and Northwind were answered perfectly with the full schema and no hints, retry never fired (retry rate 0). They did not discriminate: this is a ceiling effect, so these results show the pipeline works on other schemas, not that any component helps there. The model has probably seen both schemas.
- Value-format traps (`PENELOPE` stored upper case, `UK` for "United Kingdom", `Discontinued` stored as text '1') were all handled on the first attempt, because the 3 sample values shown per column carry the format. Value linking would not have changed anything here.
- The one router miss: s05 ("total payment revenue in June 2005") went to Lahman by 0.435 vs 0.426 (it matches Lahman's year columns). The answerable gate then refused it ("no payment tables"), so the miss produced a refusal rather than a wrong answer.
- Remaining failures are the same as before: q13 (Appearances vs Batting) and q03 (false refusal on "last season").
