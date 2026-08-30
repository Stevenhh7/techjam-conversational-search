from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedTurn:
    intent: str
    buying_probability: float
    category: str | None = None
    constraints: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    override: bool = False
    no_preference_attribute: str | None = None


@dataclass
class SessionState:
    session_id: str
    user_profile: dict
    turn: int = 0
    intent: str = "browsing"
    buying_probability: float = 0.5
    category: str | None = None
    hard_constraints: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    exclusions: set[str] = field(default_factory=set)
    asked_attributes: set[str] = field(default_factory=set)
    unavailable_attributes: set[str] = field(default_factory=set)
    previous_recommendations: list[str] = field(default_factory=list)
    message_history: list[str] = field(default_factory=list)
    budget_min: float | None = None
    budget_max: float | None = None

