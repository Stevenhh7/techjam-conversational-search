from __future__ import annotations

from solution.config import SolutionConfig
from solution.schemas import RoutingDecision, SessionState


def route_intent(state: SessionState, config: SolutionConfig) -> RoutingDecision:
    """Translate intent probability and confirmed state into an executable track."""

    buying = state.buying_probability >= config.buying_threshold
    confidence = state.buying_probability if buying else 1.0 - state.buying_probability
    reasons: list[str] = [f"buying_probability={state.buying_probability:.2f}"]
    if state.hard_constraints:
        reasons.append("confirmed_hard_constraints")
    if state.turn > 1:
        reasons.append("multi_turn_state")

    if buying:
        return RoutingDecision(
            intent="buying",
            confidence=confidence,
            track="precision",
            hard_filtering=True,
            category_strictness="strong",
            keyword_limit=config.candidate_limit,
            category_limit=config.buying_category_limit,
            metadata_limit=config.candidate_limit,
            dense_limit=config.buying_dense_limit,
            dense_mode=config.dense_mode,
            diversity_enabled=False,
            reasons=tuple(reasons),
        )
    return RoutingDecision(
        intent="browsing",
        confidence=confidence,
        track="discovery",
        hard_filtering=False,
        category_strictness="soft",
        keyword_limit=config.candidate_limit,
        category_limit=config.browsing_category_limit,
        metadata_limit=config.candidate_limit,
        dense_limit=config.browsing_dense_limit,
        dense_mode="rrf" if config.dense_mode == "rrf" else "semantic_pool",
        diversity_enabled=config.browsing_diversity_enabled,
        reasons=tuple(reasons),
    )
