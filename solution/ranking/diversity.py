from __future__ import annotations

from collections import Counter

from solution.catalog import leaf_category, normalize_text
from solution.retrieval.base import Candidate


GENERIC_CATEGORIES = {"", "clothing", "clothing item", "product", "products", "item"}


def is_open_category(category: str | None) -> bool:
    return normalize_text(category) in GENERIC_CATEGORIES


def diversify_categories(
    candidates: list[Candidate],
    products: dict[str, dict],
    strength: float,
) -> list[Candidate]:
    """Greedy relevance-preserving category diversification for open browsing queries."""

    if strength <= 0.0 or len(candidates) < 2:
        return candidates
    remaining = list(candidates)
    selected: list[Candidate] = []
    category_counts: Counter[str] = Counter()
    while remaining:
        best_index = 0
        best_key: tuple[float, float, str] | None = None
        for index, candidate in enumerate(remaining):
            category = normalize_text(leaf_category(products[candidate.parent_asin])) or "unknown"
            adjusted = candidate.score - strength * category_counts[category]
            key = (adjusted, candidate.score, candidate.parent_asin)
            if best_key is None or key > best_key:
                best_key = key
                best_index = index
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        category = normalize_text(leaf_category(products[chosen.parent_asin])) or "unknown"
        category_counts[category] += 1
    return selected
