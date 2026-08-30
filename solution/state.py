from __future__ import annotations

import re

from solution.intent import parse_turn
from solution.schemas import SessionState


PRICE_RE = re.compile(r"(?:\$|budget(?:\s+around)?\s*\$?)(\d+(?:\.\d+)?)", re.I)


def _append_unique(values: list[str], incoming: list[str]) -> None:
    known = {value.lower() for value in values}
    for value in incoming:
        if value.lower() not in known:
            values.append(value)
            known.add(value.lower())


def update_state(state: SessionState, message: str, turn: int) -> SessionState:
    parsed = parse_turn(message, state.intent)
    state.turn = turn
    state.message_history.append(message)
    state.buying_probability = parsed.buying_probability
    if parsed.intent != "override":
        state.intent = parsed.intent
    if parsed.category:
        state.category = parsed.category
    if parsed.no_preference_attribute:
        state.unavailable_attributes.add(parsed.no_preference_attribute)
    state.exclusions.update(parsed.exclusions)

    if parsed.override:
        state.intent = "buying"
        state.soft_preferences.clear()
        state.hard_constraints.clear()
        _append_unique(state.hard_constraints, parsed.constraints)
    elif parsed.constraints:
        target = state.hard_constraints if state.intent == "buying" else state.soft_preferences
        _append_unique(target, parsed.constraints)

    for constraint in parsed.constraints:
        match = PRICE_RE.search(constraint)
        if match:
            value = float(match.group(1))
            if any(marker in constraint.lower() for marker in ("under", "maximum", "max", "<=")):
                state.budget_max = value
            elif "around" in constraint.lower():
                state.budget_min, state.budget_max = value * 0.7, value * 1.3
    return state

