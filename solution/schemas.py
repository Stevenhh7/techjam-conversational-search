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


@dataclass(frozen=True)
class Constraint:
    """A catalog-grounded preference extracted from one user turn."""

    attribute: str
    operator: str
    value: str
    confidence: float
    source_turn: int
    hard: bool
    raw: str = ""


@dataclass(frozen=True)
class RoutingDecision:
    """Executable two-track routing decision for a single response."""

    intent: str
    confidence: float
    track: str
    hard_filtering: bool
    category_strictness: str
    keyword_limit: int
    category_limit: int
    metadata_limit: int
    dense_limit: int
    dense_mode: str
    diversity_enabled: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticCandidate:
    """Small, catalog-grounded candidate payload exposed to a future LLM."""

    parent_asin: str
    title: str
    category: str
    attributes: str
    deterministic_score: float
    route_ranks: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class SlotMutation:
    """Auditable slot-store change produced by one user turn."""

    turn: int
    action: str
    attribute: str
    old_values: tuple[str, ...]
    new_values: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class DialogueTransition:
    turn: int
    from_phase: str
    to_phase: str
    reason: str


@dataclass(frozen=True)
class OverGeneralityDecision:
    overloaded: bool
    confidence: float
    reasons: tuple[str, ...]
    unique_candidate_count: int
    saturated_routes: tuple[str, ...]
    query_term_count: int
    active_slot_count: int


@dataclass(frozen=True)
class ClarificationDecision:
    attribute: str | None
    score: float
    reason: str
    coverage: float
    entropy: float
    expected_reduction: float
    example_values: tuple[str, ...]
    prompt: str | None


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
    structured_constraints: list[Constraint] = field(default_factory=list)
    last_routing: RoutingDecision | None = None
    slot_store: dict[str, list[Constraint]] = field(default_factory=dict)
    slot_history: list[SlotMutation] = field(default_factory=list)
    dialogue_phase: str = "new"
    transition_history: list[DialogueTransition] = field(default_factory=list)
    state_revision: int = 0
    last_processed_turn: int = 0
    last_processed_message: str | None = None
    pending_clarification: ClarificationDecision | None = None
    over_generality: OverGeneralityDecision | None = None

