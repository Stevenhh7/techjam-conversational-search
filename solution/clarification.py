from __future__ import annotations

import math
from collections import Counter

from solution.catalog import product_attribute_values
from solution.schemas import ClarificationDecision, SessionState


ALLOWED_ATTRIBUTES = ("category", "material", "color", "size", "style", "brand", "budget", "feature", "use_case")
POLICY_PRIOR = {
    "category": 0.8, "material": 1.0, "color": 0.85, "size": 0.72, "style": 0.95,
    "brand": 0.55, "budget": 0.72, "feature": 1.25, "use_case": 1.05,
}
QUESTION = {
    "category": "Which product category should I prioritize?",
    "material": "Do you have a preferred material, such as cotton, leather, or polyester?",
    "color": "Which color should I prioritize?",
    "size": "Do you have a required size or fit?",
    "style": "Do you prefer a casual, athletic, or formal style?",
    "brand": "Is there a brand you prefer?",
    "budget": "What budget range should I stay within?",
    "feature": "Which feature matters most, such as comfort, durability, or weather protection?",
    "use_case": "What activity or occasion will you use it for?",
}


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values() if count)


def _proactive_prompt(
    state: SessionState,
    attribute: str,
    examples: tuple[str, ...],
) -> str:
    known = [
        f"{constraint.attribute} {constraint.value}"
        for constraint in state.structured_constraints[:3]
    ]
    prefix = "I'm seeing a broad set of possible matches."
    if known:
        prefix += " I'll keep " + ", ".join(known) + "."
    question = QUESTION[attribute]
    if examples:
        rendered = ", ".join(value.replace("_", " ") for value in examples)
        return f"{prefix} {question} Common options in the current results include {rendered}."
    return f"{prefix} {question}"


def choose_clarification(
    state: SessionState,
    ranked_ids: list[str],
    products: dict[str, dict],
    proactive: bool = False,
    allow_late: bool = False,
) -> ClarificationDecision:
    if state.turn >= 8 and not allow_late:
        return ClarificationDecision(None, 0.0, "question_window_closed", 0.0, 0.0, 0.0, (), None)
    blocked = state.asked_attributes | state.unavailable_attributes
    if state.category:
        blocked.add("category")
    candidate_ids = ranked_ids[:50]
    if not candidate_ids:
        attribute = next((value for value in ALLOWED_ATTRIBUTES if value not in blocked), None)
        prompt = _proactive_prompt(state, attribute, ()) if proactive and attribute else question_for(attribute)
        return ClarificationDecision(
            attribute,
            0.0,
            "no_retrieval_candidates",
            0.0,
            0.0,
            0.0,
            (),
            prompt,
        )
    best: tuple[float, str, float, float, float, Counter[str]] | None = None
    for attribute in ALLOWED_ATTRIBUTES:
        if attribute in blocked:
            continue
        counts: Counter[str] = Counter()
        covered = 0
        for parent_asin in candidate_ids:
            values = product_attribute_values(products[parent_asin]).get(attribute, set())
            if values:
                covered += 1
                counts.update(values)
        coverage = covered / len(candidate_ids)
        if coverage < 0.08:
            continue
        entropy = _entropy(counts)
        diversity = min(1.0, entropy / 3.0)
        expected_reduction = 1.0 - (max(counts.values(), default=covered) / max(1, sum(counts.values())))
        score = coverage * (0.45 + 0.55 * diversity) * (0.5 + 0.5 * expected_reduction) * POLICY_PRIOR[attribute]
        if best is None or score > best[0] or (score == best[0] and attribute < best[1]):
            best = (score, attribute, coverage, entropy, expected_reduction, counts)
    if best is None:
        attribute = next((a for a in ("feature", "style", "material", "color") if a not in blocked), None)
        prompt = _proactive_prompt(state, attribute, ()) if proactive and attribute else question_for(attribute)
        return ClarificationDecision(
            attribute,
            0.0,
            "fallback_policy_prior",
            0.0,
            0.0,
            0.0,
            (),
            prompt,
        )
    score, attribute, coverage, entropy, expected_reduction, counts = best
    examples = tuple(value for value, _ in counts.most_common(3))
    prompt = _proactive_prompt(state, attribute, examples) if proactive else question_for(attribute)
    return ClarificationDecision(
        attribute,
        score,
        "maximum_expected_candidate_reduction",
        coverage,
        entropy,
        expected_reduction,
        examples,
        prompt,
    )


def choose_attribute(state: SessionState, ranked_ids: list[str], products: dict[str, dict]) -> str | None:
    return choose_clarification(state, ranked_ids, products).attribute


def question_for(attribute: str | None) -> str | None:
    return QUESTION.get(attribute) if attribute else None

