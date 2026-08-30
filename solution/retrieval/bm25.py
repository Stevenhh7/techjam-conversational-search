from __future__ import annotations

import sqlite3

from solution.catalog import ProductDocument, tokens
from solution.retrieval.base import Candidate


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
}


def query_terms(text: str, limit: int = 60) -> list[str]:
    result: list[str] = []
    for term in tokens(text):
        if len(term) > 1 and term not in STOPWORDS and term not in result:
            result.append(term)
        if len(result) >= limit:
            break
    return result


class BM25Retriever:
    def __init__(self, documents: list[ProductDocument]) -> None:
        self.connection = sqlite3.connect(":memory:")
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, category, brand, attributes, features, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, ...]] = []
        for doc in documents:
            batch.append((doc.parent_asin, doc.title, doc.category, doc.brand, doc.attributes, doc.features, doc.description))
            if len(batch) == 1000:
                cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        self.connection.commit()

    @staticmethod
    def _expression(text: str) -> str:
        return " OR ".join(f'"{term}"' for term in query_terms(text))

    def _search(self, query: str, limit: int, weights: tuple[float, ...]) -> list[Candidate]:
        expression = self._expression(query)
        if not expression:
            return []
        weight_sql = ", ".join(str(value) for value in weights)
        rows = self.connection.execute(
            f"SELECT parent_asin, bm25(products, {weight_sql}) AS distance "
            "FROM products WHERE products MATCH ? ORDER BY distance LIMIT ?",
            (expression, limit),
        ).fetchall()
        return [Candidate(str(row[0]), 1.0 / rank, {"raw": float(row[1])}) for rank, row in enumerate(rows, 1)]

    def search(self, query: str, limit: int) -> list[Candidate]:
        return self._search(query, limit, (0.0, 8.0, 5.0, 5.5, 4.0, 2.4, 1.0))

    def metadata_search(self, query: str, limit: int) -> list[Candidate]:
        return self._search(query, limit, (0.0, 2.0, 9.0, 8.0, 7.0, 1.2, 0.2))

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
