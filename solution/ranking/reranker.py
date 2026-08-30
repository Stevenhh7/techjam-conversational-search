from __future__ import annotations

import math

from solution.catalog import normalize_text, tokens
from solution.query_builder import BuiltQuery
from solution.ranking.constraints import passes_hard_constraints
from solution.retrieval.base import Candidate
from solution.schemas import SessionState


def _overlap(query: str, text: object) -> float:
    query_terms = set(tokens(query))
    if not query_terms:
        return 0.0
    product_terms = set(tokens(text))
    return len(query_terms & product_terms) / len(query_terms)


def rerank(
    candidates: list[Candidate],
    products: dict[str, dict],
    query: BuiltQuery,
    state: SessionState,
    weights: dict[str, float] | None = None,
) -> list[Candidate]:
    if not candidates:
        return []
    weights = weights or {
        "rrf": 0.30,
        "dense": 0.20,
        "lexical": 0.22,
        "exact": 0.12,
        "category": 0.09,
        "profile": 0.04,
        "rating": 0.03,
        "popularity": 0.0,
    }
    max_rrf = max(item.score for item in candidates) or 1.0
    scored: list[Candidate] = []
    for candidate in candidates:
        product = products[candidate.parent_asin]
        if not passes_hard_constraints(product, state):
            continue
        search_text = [product.get("title"), product.get("features"), product.get("details"), product.get("description")]
        category_text = product.get("categories")
        lexical = _overlap(query.lexical, search_text)
        category = _overlap(query.category, category_text)
        profile = _overlap(query.profile, search_text) if query.profile else 0.0
        dense = candidate.route_scores.get("dense", 0.0)
        dense = max(0.0, min(1.0, (dense + 1.0) / 2.0))
        exact = 0.0
        normalized_product = normalize_text(search_text)
        for value in (*state.hard_constraints, *state.soft_preferences):
            normalized = normalize_text(value)
            if normalized and normalized in normalized_product:
                exact += 1.0
        exact = min(1.0, exact / max(1, len(state.hard_constraints) + len(state.soft_preferences)))
        rating = float(product.get("average_rating") or 0.0) / 5.0
        popularity = min(1.0, math.log1p(float(product.get("rating_number") or 0.0)) / math.log1p(100_000.0))
        candidate.score = (
            weights["rrf"] * (candidate.score / max_rrf)
            + weights["dense"] * dense
            + weights["lexical"] * lexical
            + weights["exact"] * exact
            + weights["category"] * category
            + weights["profile"] * profile
            + weights["rating"] * rating
            + weights.get("popularity", 0.0) * popularity
        )
        scored.append(candidate)
    return sorted(scored, key=lambda item: (-item.score, item.parent_asin))
