from functools import lru_cache

from nl2sql import db

EMBED_MODEL = "all-MiniLM-L6-v2"
TOP_K = 5

# HomeGames names its keys differently; map them onto the standard names.
KEY_ALIASES = {"yearkey": "yearID", "leaguekey": "lgID", "teamkey": "teamID"}
# Too generic to justify a join on their own.
WEAK_KEYS = {"yearID", "lgID"}


def canon(col: str) -> str:
    return KEY_ALIASES.get(col, col)


def is_key(col: str) -> bool:
    c = canon(col).lower()
    return c != "id" and (c.endswith("id") or c.endswith("key"))


def key_columns(schema: dict) -> dict:
    """{table: {canonical_key: actual_column}} for key-like columns."""
    return {t: {canon(c["name"]): c["name"] for c in cols if is_key(c["name"])} for t, cols in schema.items()}


def inferred_joins(schema: dict, tables: list[str]) -> list[str]:
    """Candidate joins between the given tables from shared key names (flagged as inferred by the caller)."""
    keys = key_columns(schema)
    lines = []
    for i, a in enumerate(tables):
        for b in tables[i + 1:]:
            shared = [k for k in keys[a] if k in keys[b] and k != "lgID"]
            if any(k not in WEAK_KEYS for k in shared):
                lines.append(" AND ".join(f"{a}.{keys[a][k]} = {b}.{keys[b][k]}" for k in shared))
    return lines


def dimension_tables(schema: dict, path=None) -> dict:
    """{strong key: table} where the key (alone, or with yearID) uniquely identifies rows."""
    conn = db.connect(path)
    try:
        def unique(table, cols):
            q = ", ".join(f'"{c}"' for c in cols)
            distinct = conn.execute(f'SELECT COUNT(*) FROM (SELECT DISTINCT {q} FROM "{table}")').fetchone()[0]
            return distinct == conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        keys = key_columns(schema)
        dims = {}
        for key in {k for ks in keys.values() for k in ks if k not in WEAK_KEYS}:
            found = []
            for t, ks in keys.items():
                if key not in ks:
                    continue
                cols = [ks[key]]
                if unique(t, cols):
                    found.append(t)
                elif "yearID" in [c["name"] for c in schema[t]] and unique(t, cols + ["yearID"]):
                    found.append(t)
            if found:
                dims[key] = max(found, key=lambda t: len(schema[t]))
        return dims
    finally:
        conn.close()


def table_docs(schema: dict) -> list[tuple[str, str | None, str]]:
    """(table, column or None, text): one doc per table plus one per column, name + sampled values."""
    docs = []
    for t, cols in schema.items():
        names = ", ".join(c["name"] for c in cols)
        docs.append((t, None, f"table {t}: columns {names}"))
        for c in cols:
            vals = ", ".join(str(v) for v in c["samples"])
            docs.append((t, c["name"], f"{t}.{c['name']} ({c['type']}) e.g. {vals}"))
    return docs


class Linker:
    def __init__(self, schema: dict, k: int = TOP_K, path=None):
        from sentence_transformers import SentenceTransformer

        self.schema, self.k = schema, k
        self.dims = dimension_tables(schema, path)
        self.docs = table_docs(schema)
        self.model = SentenceTransformer(EMBED_MODEL)
        self.doc_vecs = self.model.encode([d[2] for d in self.docs], normalize_embeddings=True)

    def rank(self, question: str) -> list[tuple[str, float, str | None]]:
        """Top-k (table, score, best-matching column or None for the table description)."""
        q = self.model.encode([question], normalize_embeddings=True)[0]
        best = {}
        for (table, column, _), sim in zip(self.docs, self.doc_vecs @ q):
            if float(sim) > best.get(table, (-1.0, None))[0]:
                best[table] = (float(sim), column)
        ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[: self.k]
        return [(t, score, column) for t, (score, column) in ranked]

    def retrieve(self, question: str) -> list[str]:
        return [t for t, _, _ in self.rank(question)]

    def expand(self, tables: list[str]) -> list[str]:
        """Add the dimension table for each strong key present in the retrieved tables."""
        keys = key_columns(self.schema)
        out = list(tables)
        for t in tables:
            for k in keys[t]:
                dim = self.dims.get(k)
                if dim and dim not in out:
                    out.append(dim)
        return out

    def link(self, question: str) -> dict:
        ranked = self.rank(question)
        top = [t for t, _, _ in ranked]
        tables = self.expand(top)
        subset = {t: self.schema[t] for t in tables}
        text = db.format_schema(subset)
        joins = inferred_joins(self.schema, tables)
        if joins:
            text += "\n\nINFERRED JOINS (not declared in the database; guessed from shared column names):\n"
            text += "\n".join(joins)
        details = [{"table": t, "how": "retrieved", "score": round(s_, 3), "match": c or "(table)"}
                   for t, s_, c in ranked]
        details += [{"table": t, "how": "added (key neighbor)", "score": None, "match": ""}
                    for t in tables if t not in top]
        return {"retrieved": top, "tables": tables, "schema_text": text, "details": details, "joins": joins}


@lru_cache(maxsize=1)
def get_linker() -> Linker:
    return Linker(db.get_schema())

