from __future__ import annotations

from solution.catalog import normalize_text, product_attribute_values
from solution.retrieval.base import Candidate
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


def _matches_structured_constraint(product: dict, attribute: str, value: str) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return True
    if attribute == "brand":
        return normalized in normalize_text(product.get("store"))
    if attribute in {"material", "color", "size"}:
        values = product_attribute_values(product).get(attribute, set())
        if normalized in {normalize_text(item) for item in values}:
            return True
        full_corpus = normalize_text([
            product.get("title"),
            product.get("features"),
            product.get("details"),
            product.get("description"),
            product.get("categories"),
            product.get("store"),
        ])
        return normalized in full_corpus
    return True


def apply_precision_constraints(
    candidates: list[Candidate],
    products: dict[str, dict],
    state: SessionState,
    minimum_candidates: int,
) -> tuple[list[Candidate], tuple[str, ...], tuple[str, ...]]:
    """Apply only high-confidence, catalog-verifiable constraints with safe relaxation."""

    remaining = candidates
    applied: list[str] = []
    relaxed: list[str] = []
    eligible = [
        item
        for item in state.structured_constraints
        if item.hard
        and item.confidence >= 0.90
        and item.attribute in {"material", "color", "size", "brand"}
    ]
    for constraint in sorted(eligible, key=lambda item: (-item.confidence, item.source_turn, item.attribute)):
        filtered = [
            candidate
            for candidate in remaining
            if _matches_structured_constraint(
                products[candidate.parent_asin], constraint.attribute, constraint.value
            )
        ]
        label = f"{constraint.attribute}:{constraint.value}"
        if len(filtered) >= minimum_candidates:
            remaining = filtered
            applied.append(label)
        else:
            relaxed.append(label)
    return remaining, tuple(applied), tuple(relaxed)

