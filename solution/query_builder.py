from __future__ import annotations

from dataclasses import dataclass

from solution.catalog import normalize_text
from solution.schemas import SessionState


EXPANSIONS = {
    "sneakers": ("running shoes", "trainers", "athletic shoes"),
    "wedding": ("formal", "dress", "elegant"),
    "rain": ("waterproof", "water resistant"),
    "college": ("backpack", "casual", "durable"),
    "hiking": ("outdoor", "trail", "waterproof"),
    "winter": ("warm", "insulated", "thermal"),
}


@dataclass(frozen=True)
class BuiltQuery:
    lexical: str
    semantic: str
    category: str
    profile: str


def build_query(state: SessionState) -> BuiltQuery:
    category = normalize_text(state.category)
    constraints = normalize_text([state.hard_constraints, state.soft_preferences])
    long_term: list[str] = []
    if state.distilled_context is not None:
        conflicts = set(state.distilled_context.profile_conflict_attributes)
        long_term = [
            f"{item.attribute} {item.value}"
            for item in state.distilled_context.long_term_preferences
            if item.attribute not in conflicts
        ]
    supplied_profile = {
        key: value for key, value in state.user_profile.items() if key != "profile_id"
    }
    profile = normalize_text([supplied_profile, long_term])
    base = " ".join(part for part in (category, constraints) if part)
    expansion_terms: list[str] = []
    for key, values in EXPANSIONS.items():
        if key in base:
            expansion_terms.extend(values)
    lexical = normalize_text([base, expansion_terms])
    # Profile is a weak semantic signal; it is not allowed to overwhelm explicit requests.
    semantic = normalize_text([base, expansion_terms, profile[:240]])
    return BuiltQuery(lexical=lexical, semantic=semantic, category=category, profile=profile)
