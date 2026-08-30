from __future__ import annotations

from solution.schemas import Constraint, DialogueTransition, SessionState, SlotMutation


PHASES = {
    "new",
    "discovery",
    "clarifying",
    "constrained",
    "ready",
    "overloaded",
    "rewriting",
}


def transition_state(state: SessionState, phase: str, turn: int, reason: str) -> None:
    if phase not in PHASES:
        raise ValueError(f"unknown dialogue phase: {phase}")
    previous = state.dialogue_phase
    if previous == phase:
        return
    state.dialogue_phase = phase
    state.transition_history.append(
        DialogueTransition(
            turn=turn,
            from_phase=previous,
            to_phase=phase,
            reason=reason,
        )
    )


def record_slot_mutation(
    state: SessionState,
    turn: int,
    action: str,
    attribute: str,
    old_values: list[str] | tuple[str, ...],
    new_values: list[str] | tuple[str, ...],
    reason: str,
) -> None:
    state.slot_history.append(
        SlotMutation(
            turn=turn,
            action=action,
            attribute=attribute,
            old_values=tuple(old_values),
            new_values=tuple(new_values),
            reason=reason,
        )
    )


def rebuild_slot_store(state: SessionState) -> None:
    store: dict[str, list[Constraint]] = {}
    for constraint in state.structured_constraints:
        store.setdefault(constraint.attribute, []).append(constraint)
    state.slot_store = store


def finish_turn_state(state: SessionState, turn: int, override_applied: bool) -> None:
    if state.structured_constraints or state.category:
        transition_state(
            state,
            "constrained",
            turn,
            "override_rewritten" if override_applied else "confirmed_slots_available",
        )
    else:
        transition_state(state, "discovery", turn, "insufficient_confirmed_slots")
