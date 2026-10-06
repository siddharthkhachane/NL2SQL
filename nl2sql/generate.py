import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = "gpt-4o"

PROMPT = """You write SQLite queries over the Lahman baseball database.

Schema (each column shows its type and a few sample values):
{schema}

Question: {question}

Return only one SQLite SELECT statement. No explanation, no markdown."""


def strip_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip()


def generate_sql(question: str, schema_text: str, model: str | None = None) -> str:
    resp = OpenAI().chat.completions.create(
        model=model or os.getenv("NL2SQL_MODEL", DEFAULT_MODEL),
        messages=[{"role": "user", "content": PROMPT.format(schema=schema_text, question=question)}],
    )
    return strip_fences(resp.choices[0].message.content)
