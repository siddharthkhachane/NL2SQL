from functools import lru_cache

from nl2sql import databases
from nl2sql.linking import get_model, table_docs

TOP_N = 3


class Router:
    """Picks which database a question belongs to, before any table-level linking.

    Each database is scored by the mean of its TOP_N best-matching table/column descriptions.
    """

    def __init__(self, names: list[str] | None = None):
        self.names = names or databases.available()
        self.model = get_model()
        self.vecs = {}
        for name in self.names:
            docs = [text for _, _, text in table_docs(databases.schema(name))]
            self.vecs[name] = self.model.encode(docs, normalize_embeddings=True)

    def scores(self, question: str) -> dict[str, float]:
        q = self.model.encode([question], normalize_embeddings=True)[0]
        out = {}
        for name, vecs in self.vecs.items():
            top = sorted((vecs @ q).tolist(), reverse=True)[:TOP_N]
            out[name] = round(sum(top) / len(top), 3)
        return out

    def route(self, question: str) -> tuple[str, dict[str, float]]:
        scores = self.scores(question)
        return max(scores, key=scores.get), scores


@lru_cache(maxsize=1)
def get_router() -> Router:
    return Router()
