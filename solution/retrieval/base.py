from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    parent_asin: str
    score: float
    route_scores: dict[str, float] = field(default_factory=dict)
    route_ranks: dict[str, int] = field(default_factory=dict)

