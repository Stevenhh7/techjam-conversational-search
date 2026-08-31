from __future__ import annotations

import re

from solution.constraint_parser import classify_constraint
from solution.context.schemas import ProfileMutation
from solution.schemas import SessionState


REMEMBER_RE = re.compile(r"\bremember(?: that)?\s+(.+?)[.!]?$", re.I)
FORGET_RE = re.compile(r"\b(?:forget|don['’]t remember)(?: that)?\s+(.+?)[.!]?$", re.I)
SESSION_ONLY_MARKERS = ("gift for", "for someone else", "for my friend", "for my partner")
REJECTION_MARKERS = ("none of these", "not what i want", "don't like", "do not like", "wrong products")
NO_PREFERENCE_RE = re.compile(r"\bno (?:additional )?preference for ([a-z_]+)\b", re.I)


def profile_mutations(state: SessionState, message: str) -> tuple[ProfileMutation, ...]:
    """Return minimal mutations. Caller must reject persistence without profile_id."""

    if any(marker in message.lower() for marker in SESSION_ONLY_MARKERS):
        return ()
    forget = FORGET_RE.search(message)
    if forget:
        if forget.group(1).strip().lower() in {"all", "everything", "my preferences"}:
            return (ProfileMutation("forget", "*", "", 1.0, state.turn, state.session_id),)
        attribute, value, _ = classify_constraint(forget.group(1))
        return (ProfileMutation("forget", attribute, value, 1.0, state.turn, state.session_id),)
    no_preference = NO_PREFERENCE_RE.search(message)
    if no_preference:
        return (
            ProfileMutation(
                "forget",
                no_preference.group(1).lower(),
                "",
                1.0,
                state.turn,
                state.session_id,
            ),
        )
    remember = REMEMBER_RE.search(message)
    if remember:
        attribute, value, confidence = classify_constraint(remember.group(1))
        return (ProfileMutation("remember", attribute, value, confidence, state.turn, state.session_id),)
    return tuple(
        ProfileMutation(
            "observe",
            item.attribute,
            item.value,
            item.confidence,
            state.turn,
            state.session_id,
        )
        for item in state.structured_constraints
        if item.source_turn == state.turn
    )


def user_rejected(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in REJECTION_MARKERS)
