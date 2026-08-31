from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreferenceEvidence:
    """Minimal structured preference evidence; raw dialogue is never persisted."""

    attribute: str
    value: str
    polarity: str
    explicit: bool
    confidence: float
    source_turn: int
    source_session: str
    session_only: bool
    durable: bool
    updated_revision: int
    confirmations: int = 1


@dataclass(frozen=True)
class LongTermProfile:
    profile_id: str
    summary: str = ""
    preferences: tuple[PreferenceEvidence, ...] = ()
    revision: int = 0


@dataclass(frozen=True)
class ProfileMutation:
    action: str
    attribute: str
    value: str = ""
    confidence: float = 1.0
    source_turn: int = 0
    source_session: str = ""


@dataclass(frozen=True)
class DistilledContext:
    core_goal: str
    intent: str
    intent_confidence: float
    confirmed_preferences: tuple[PreferenceEvidence, ...]
    tentative_preferences: tuple[PreferenceEvidence, ...]
    negative_preferences: tuple[PreferenceEvidence, ...]
    session_preferences: tuple[PreferenceEvidence, ...]
    long_term_preferences: tuple[PreferenceEvidence, ...]
    unresolved_attributes: tuple[str, ...]
    recent_override: bool
    recommended_candidates: tuple[str, ...]
    rejected_candidates: tuple[str, ...]
    recent_strategy_outcomes: tuple[str, ...]
    recent_messages: tuple[str, ...]
    profile_conflict_attributes: tuple[str, ...]
    no_progress_turns: int
    consecutive_llm_failures: int
    summary: str
    context_revision: int
