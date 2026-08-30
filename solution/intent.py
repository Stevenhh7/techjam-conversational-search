from __future__ import annotations

import re

from solution.catalog import normalize_text
from solution.schemas import ParsedTurn


BUYING_MARKERS = ("key requirement", "i need", "must", "under $", "size ", "what i need")
BROWSING_MARKERS = ("still exploring", "not sure", "show me ideas", "use your judgment", "something for", "gift for")


def _payload(message: str) -> str | None:
    if ":" not in message:
        return None
    value = message.split(":", 1)[1].strip(" .")
    if not value or value.lower().startswith("please use your judgment"):
        return None
    return value


def parse_turn(message: str, previous_intent: str = "browsing") -> ParsedTurn:
    lowered = message.lower()
    override = (
        ("actually" in lowered and ("ignore" in lowered or "instead" in lowered))
        or "instead of" in lowered
        or bool(re.search(r"\b(?:change|switch)\b.*?\bto\b", lowered))
    )
    no_pref = re.search(r"no (?:additional )?preference for ([a-z_]+)", lowered)
    category_match = re.search(r"looking for (.*?)(?:[,.]|$)", message, re.I)
    category = category_match.group(1).strip() if category_match else None
    if category and " instead of " in category.lower():
        category = re.split(r"\s+instead of\s+", category, maxsplit=1, flags=re.I)[0].strip()
    buying_hits = sum(marker in lowered for marker in BUYING_MARKERS)
    browsing_hits = sum(marker in lowered for marker in BROWSING_MARKERS)
    if override:
        intent = "override"
        buying_probability = 0.9
    elif buying_hits > browsing_hits:
        intent = "buying"
        buying_probability = min(0.95, 0.64 + 0.1 * buying_hits)
    elif browsing_hits:
        intent = "browsing"
        buying_probability = max(0.1, 0.36 - 0.08 * browsing_hits)
    else:
        intent = previous_intent
        buying_probability = 0.7 if previous_intent == "buying" else 0.42

    constraints: list[str] = []
    payload = _payload(message)
    if payload and not lowered.startswith("i don't have"):
        constraints = [part.strip(" .") for part in payload.split(";") if normalize_text(part)]
    exclusions = re.findall(r"\b(?:not|without|exclude)\s+([a-z0-9 -]{2,30})", lowered)
    exclusions = [
        value
        for value in exclusions
        if not value.startswith(("quite right", "sure", "an additional preference"))
    ]
    return ParsedTurn(
        intent=intent,
        buying_probability=buying_probability,
        category=category,
        constraints=constraints,
        exclusions=exclusions,
        override=override,
        no_preference_attribute=no_pref.group(1) if no_pref else None,
    )

