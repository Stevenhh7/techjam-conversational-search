from __future__ import annotations

from collections import defaultdict

from solution.catalog import ProductDocument, normalize_text, tokens
from solution.retrieval.base import Candidate


class CategoryRetriever:
    """Small in-memory inverted index dedicated to catalog category paths."""

    def __init__(self, documents: list[ProductDocument]) -> None:
        self.categories: dict[str, str] = {}
        self.category_tokens: dict[str, frozenset[str]] = {}
        postings: dict[str, list[str]] = defaultdict(list)
        for document in documents:
            category = normalize_text(document.raw.get("categories"))
            values = frozenset(tokens(category))
            self.categories[document.parent_asin] = category
            self.category_tokens[document.parent_asin] = values
            for value in values:
                postings[value].append(document.parent_asin)
        self.postings = {key: tuple(values) for key, values in postings.items()}

    def search(self, query: str, limit: int) -> list[Candidate]:
        normalized = normalize_text(query)
        query_tokens = frozenset(tokens(normalized))
        if not query_tokens or limit <= 0:
            return []
        identifiers: set[str] = set()
        for value in query_tokens:
            identifiers.update(self.postings.get(value, ()))
        scored: list[tuple[str, float]] = []
        for parent_asin in identifiers:
            values = self.category_tokens[parent_asin]
            overlap = len(query_tokens & values) / len(query_tokens)
            exact_bonus = 0.35 if normalized and normalized in self.categories[parent_asin] else 0.0
            scored.append((parent_asin, overlap + exact_bonus))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [
            Candidate(parent_asin, score, {"category": score})
            for parent_asin, score in scored[:limit]
        ]
