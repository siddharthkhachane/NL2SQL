# NL2SQL on Lahman

## Run

- Tests: `uv run pytest`
- Eval: `uv run python eval/run_eval.py` (results saved to `eval/results/<timestamp>.json`)
- App: `uv run streamlit run app.py`

## Safety rules

- Model-generated SQL runs only through the safe executor in `nl2sql/db.py`.
- Exactly one statement, and it must be SELECT.
- SQLite is opened read-only (`file:...?mode=ro`), with a row limit (default 100) and a query timeout.
- API key comes only from `.env`; model name from `NL2SQL_MODEL` (default `claude-sonnet-5-5`).
- Never commit `.env`, API keys, or `data/*.sqlite`.
- Do not write gold SQL without showing its row count and a sample result.
- Log surprises in `NOTES.md`.

## Workflow

One phase at a time. At the end of each phase, summarize what changed, how to verify it, and what could still be wrong, then stop and wait for approval. Test, then commit after each phase.
