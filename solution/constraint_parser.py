from __future__ import annotations

import re

from solution.catalog import COLORS, MATERIALS, USE_CASES, normalize_text
from solution.schemas import Constraint


SIZE_RE = re.compile(r"\b(?:size\s*)?(xxs|xs|s|m|l|xl|xxl|\d{1,2}(?:\.5)?)\b", re.I)
ATTRIBUTE_PREFIX_RE = re.compile(
    r"^(?:color|colour|material|brand|size|style|feature|department|budget|price)\s*[:=-]\s*",
    re.I,
)
FULL_OVERRIDE_MARKERS = (
    "ignore my earlier preference",
    "ignore everything",
    "forget everything",
    "start over",
)


def _first_known(text: str, values: tuple[str, ...]) -> str | None:
    normalized = normalize_text(text)
    return next(
        (value for value in values if re.search(rf"\b{re.escape(value)}\b", normalized)),
        None,
    )


def classify_constraint(value: str) -> tuple[str, str, float]:
    """Classify simulator and natural-language constraint text conservatively."""

    normalized = normalize_text(value)
    lowered = value.lower()
    if "budget" in lowered or "price" in lowered or re.search(r"(?:\$|<=|under|max(?:imum)?)\s*\d", lowered):
        return "budget", normalized, 0.98
    material = _first_known(value, MATERIALS)
    if material:
        return "material", material, 0.96
    color = _first_known(value, COLORS)
    if color:
        return "color", color, 0.96
    size = SIZE_RE.search(lowered)
    if "size" in lowered and size:
        return "size", normalize_text(size.group(1)), 0.95
    use_case = _first_known(value, USE_CASES)
    if use_case:
        return "use_case", use_case, 0.88
    if "brand" in lowered or "store" in lowered:
        return "brand", normalize_text(ATTRIBUTE_PREFIX_RE.sub("", value)), 0.90
    if any(marker in lowered for marker in ("department", "style", "fit", "sleeve", "neck")):
        return "style", normalize_text(ATTRIBUTE_PREFIX_RE.sub("", value)), 0.82
    return "feature", normalize_text(ATTRIBUTE_PREFIX_RE.sub("", value)), 0.78


def build_constraints(
    values: list[str],
    turn: int,
    hard: bool,
    expected_attribute: str | None = None,
) -> list[Constraint]:
    result: list[Constraint] = []
    seen: set[tuple[str, str]] = set()
    for raw in values:
        attribute, value, confidence = classify_constraint(raw)
        explicit_attribute = bool(ATTRIBUTE_PREFIX_RE.match(raw))
        if expected_attribute and not explicit_attribute and attribute != "budget":
            attribute = expected_attribute
            value = normalize_text(ATTRIBUTE_PREFIX_RE.sub("", raw))
            confidence = 0.92
        key = (attribute, value)
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(
            Constraint(
                attribute=attribute,
                operator="lte" if attribute == "budget" and "under" in raw.lower() else "contains",
                value=value,
                confidence=confidence,
                source_turn=turn,
                hard=hard,
                raw=raw,
            )
        )
    return result


def constraint_key(constraint: Constraint) -> tuple[str, str, str]:
    return constraint.attribute, constraint.operator, constraint.value


def rewrite_values(message: str) -> list[str]:
    """Extract the replacement side of common attribute-level correction forms."""

    text = message.strip(" .")
    lowered = text.lower()
    if "instead of" in lowered:
        index = lowered.index("instead of")
        value = text[:index]
        value = re.sub(r"^(?:actually|no|please|make it)\s*[,;:-]?\s*", "", value, flags=re.I)
        return [value.strip(" ,;:-")] if normalize_text(value) else []
    match = re.search(r"\b(?:change|switch)\b.*?\bto\b\s+(.+)$", text, re.I)
    if match:
        return [match.group(1).strip(" .")]
    match = re.search(r"\binstead\b\s*[,;:-]?\s*(.+)$", text, re.I)
    if match:
        return [match.group(1).strip(" .")]
    return []


def override_scope(message: str, constraints: list[Constraint], category_changed: bool) -> str:
    lowered = message.lower()
    if any(marker in lowered for marker in FULL_OVERRIDE_MARKERS):
        return "full"
    if category_changed:
        return "category"
    if constraints and any(marker in lowered for marker in ("instead", "change", "switch", "rather")):
        attributes = {item.attribute for item in constraints}
        return "attribute" if len(attributes) == 1 else "full"
    return "full"
