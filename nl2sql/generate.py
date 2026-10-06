import json
import os
import re
from datetime import date

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = "gpt-4o"

PROMPT = """You write SQLite queries over the Lahman baseball database.

Schema (each column shows its type and a few sample values):
{schema}

Question: {question}
"""

SQL_ONLY = "\nReturn only one SQLite SELECT statement. No explanation, no markdown."

ASSUMPTIONS_NOTE = (
    "assumptions: one sentence on how you resolved any ambiguity in the question (for example which player, "
    "what 'last season' or 'latest' means, team vs franchise), or 'none'. Today is {today}; the data ends in 2025 "
    "and the Salaries table ends in 2016."
)
GATE_NOTE = (
    "answerable: false if the database cannot answer the question (for example it needs play-by-play, pitch-level "
    "or future data that no table holds), otherwise true. If false, set sql to an empty string and use "
    "assumptions to say why."
)


def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip()


def _complete(prompt: str, model: str | None = None, json_mode: bool = False) -> str:
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = OpenAI(max_retries=8).chat.completions.create(
        model=model or os.getenv("NL2SQL_MODEL", DEFAULT_MODEL),
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        **extra,
    )
    return resp.choices[0].message.content


def retry_feedback(previous_sql: str, error: str | None) -> str:
    problem = f"failed with the error: {error}" if error else \
        "returned no rows; re-check the filters, literal values and joins"
    return f"\nYour previous attempt was:\n{previous_sql}\nIt {problem}. Write a corrected query.\n"


def generate_sql(question: str, schema_text: str, model: str | None = None, feedback: str | None = None) -> str:
    prompt = PROMPT.format(schema=schema_text, question=question) + (feedback or "") + SQL_ONLY
    return strip_fences(_complete(prompt, model))


def generate_structured(question: str, schema_text: str, assumptions: bool, gate: bool,
                        model: str | None = None, feedback: str | None = None) -> dict:
    """JSON reply: {sql, [assumptions], [answerable]} depending on the flags."""
    fields = ["sql: one SQLite SELECT statement"]
    if assumptions:
        fields.append(ASSUMPTIONS_NOTE.format(today=date.today().isoformat()))
    if gate:
        fields.append(GATE_NOTE)
    prompt = (PROMPT.format(schema=schema_text, question=question) + (feedback or "")
              + "\nReply with a JSON object with these keys:\n- " + "\n- ".join(fields))
    text = _complete(prompt, model, json_mode=True)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"sql": strip_fences(text)}
    data["sql"] = strip_fences(str(data.get("sql") or ""))
    return data
