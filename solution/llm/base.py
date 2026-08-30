from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from solution.schemas import Constraint, RoutingDecision, SemanticCandidate


@dataclass(frozen=True)
class SemanticRankRequest:
    query: str
    routing: RoutingDecision
    constraints: tuple[Constraint, ...]
    profile_summary: str
    candidates: tuple[SemanticCandidate, ...]


@dataclass(frozen=True)
class SemanticRankResult:
    ordered_parent_asins: tuple[str, ...]
    applied: bool
    reason: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


class SemanticRanker(Protocol):
    def rank(self, request: SemanticRankRequest) -> SemanticRankResult:
        ...

    def status(self) -> dict[str, object]:
        ...

    def close(self) -> None:
        ...
