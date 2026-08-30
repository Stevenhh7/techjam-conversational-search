from __future__ import annotations

from solution.catalog import normalize_text
from solution.schemas import SessionState


def passes_hard_constraints(product: dict, state: SessionState) -> bool:
    corpus = normalize_text([product.get("title"), product.get("features"), product.get("details"), product.get("categories")])
    if any(normalize_text(value) and normalize_text(value) in corpus for value in state.exclusions):
        return False
    price = product.get("price")
    if state.budget_max is not None and isinstance(price, (int, float)) and price > state.budget_max:
        return False
    if state.budget_min is not None and isinstance(price, (int, float)) and price < state.budget_min:
        return False
    return True

