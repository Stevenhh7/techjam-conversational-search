from __future__ import annotations

import re

from solution.catalog import normalize_text
from solution.constraint_parser import (
    build_constraints,
    classify_constraint,
    constraint_key,
    override_scope,
    rewrite_values,
)
from solution.intent import parse_turn
from solution.schemas import Constraint, SessionState
from solution.state_machine import (
    finish_turn_state,
    rebuild_slot_store,
    record_slot_mutation,
    transition_state,
)


PRICE_RE = re.compile(r"(?:\$|budget(?:\s+around)?\s*\$?)(\d+(?:\.\d+)?)", re.I)


def _append_unique(values: list[str], incoming: list[str]) -> None:
    known = {value.lower() for value in values}
    for value in incoming:
        if value.lower() not in known:
            values.append(value)
            known.add(value.lower())


def _remove_legacy_attributes(values: list[str], attributes: set[str]) -> None:
    values[:] = [
        value
        for value in values
        if classify_constraint(value)[0] not in attributes
    ]


def _remove_structured_attributes(state: SessionState, attributes: set[str]) -> None:
    state.structured_constraints[:] = [
        item for item in state.structured_constraints if item.attribute not in attributes
    ]


def _add_structured_constraints(
    state: SessionState,
    incoming: list[Constraint],
    turn: int,
    action: str,
    reason: str,
) -> None:
    known = {constraint_key(item) for item in state.structured_constraints}
    for constraint in incoming:
        if constraint_key(constraint) in known:
            continue
        state.structured_constraints.append(constraint)
        known.add(constraint_key(constraint))
        record_slot_mutation(
            state,
            turn,
            action,
            constraint.attribute,
            (),
            (constraint.value,),
            reason,
        )


def _apply_budget(state: SessionState, values: list[str]) -> None:
    for constraint in values:
        match = PRICE_RE.search(constraint)
        if not match:
            continue
        value = float(match.group(1))
        if any(marker in constraint.lower() for marker in ("under", "maximum", "max", "<=")):
            state.budget_max = value
        elif "around" in constraint.lower():
            state.budget_min, state.budget_max = value * 0.7, value * 1.3


def update_state(state: SessionState, message: str, turn: int) -> SessionState:
    if turn < state.last_processed_turn:
        raise RuntimeError("stale turn cannot rewrite newer conversation state")
    if turn == state.last_processed_turn:
        if message == state.last_processed_message:
            return state
        raise RuntimeError("the same turn cannot be processed with a different message")

    parsed = parse_turn(message, state.intent)
    expected_attribute = (
        state.pending_clarification.attribute
        if state.pending_clarification is not None and not parsed.override
        else None
    )
    old_category = state.category
    category_changed = bool(
        parsed.category
        and old_category
        and normalize_text(parsed.category) != normalize_text(old_category)
    )
    values = list(parsed.constraints)
    if parsed.override and not values and not parsed.category:
        values = rewrite_values(message)
    incoming = build_constraints(
        values,
        turn=turn,
        hard=parsed.override or parsed.intent == "buying" or state.intent == "buying",
        expected_attribute=expected_attribute,
    )

    state.turn = turn
    state.pending_clarification = None
    state.over_generality = None
    state.message_history.append(message)
    state.buying_probability = parsed.buying_probability
    if parsed.intent != "override":
        state.intent = parsed.intent
    if parsed.category:
        state.category = parsed.category
    elif expected_attribute == "category" and incoming:
        state.category = incoming[0].value
    if parsed.no_preference_attribute:
        state.unavailable_attributes.add(parsed.no_preference_attribute)

    if parsed.override:
        transition_state(state, "rewriting", turn, "intent_override_detected")
        state.intent = "buying"
        scope = override_scope(message, incoming, category_changed)
        if scope == "full":
            for attribute, constraints in sorted(state.slot_store.items()):
                record_slot_mutation(
                    state,
                    turn,
                    "reset",
                    attribute,
                    [item.value for item in constraints],
                    (),
                    "full_intent_override",
                )
            state.soft_preferences.clear()
            state.hard_constraints.clear()
            state.structured_constraints.clear()
            state.exclusions.clear()
            state.budget_min = None
            state.budget_max = None
        elif scope == "attribute":
            attributes = {item.attribute for item in incoming}
            for attribute in sorted(attributes):
                old_values = [
                    item.value
                    for item in state.structured_constraints
                    if item.attribute == attribute
                ]
                record_slot_mutation(
                    state,
                    turn,
                    "replace",
                    attribute,
                    old_values,
                    [item.value for item in incoming if item.attribute == attribute],
                    "attribute_level_override",
                )
            _remove_structured_attributes(state, attributes)
            _remove_legacy_attributes(state.hard_constraints, attributes)
            _remove_legacy_attributes(state.soft_preferences, attributes)
            if "budget" in attributes:
                state.budget_min = None
                state.budget_max = None
        elif scope == "category":
            dependent = {"category", "size", "style"}
            record_slot_mutation(
                state,
                turn,
                "replace",
                "category",
                (old_category,) if old_category else (),
                (parsed.category,) if parsed.category else (),
                "category_override",
            )
            _remove_structured_attributes(state, dependent)
            _remove_legacy_attributes(state.hard_constraints, dependent)
            _remove_legacy_attributes(state.soft_preferences, dependent)
        _append_unique(state.hard_constraints, values)
        _add_structured_constraints(
            state,
            incoming,
            turn,
            "add" if scope == "full" else "replace_value",
            f"{scope}_override_value",
        )
    elif values:
        target = state.hard_constraints if state.intent == "buying" else state.soft_preferences
        _append_unique(target, values)
        _add_structured_constraints(state, incoming, turn, "add", "incremental_information")

    state.exclusions.update(parsed.exclusions)
    _apply_budget(state, values)
    rebuild_slot_store(state)
    finish_turn_state(state, turn, parsed.override)
    state.state_revision += 1
    state.last_processed_turn = turn
    state.last_processed_message = message
    return state

