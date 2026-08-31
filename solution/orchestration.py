from __future__ import annotations

from dataclasses import dataclass, replace

from solution.config import SolutionConfig
from solution.context.schemas import DistilledContext
from solution.retrieval.base import Candidate
from solution.schemas import RoutingDecision


@dataclass(frozen=True)
class ContextProgram:
    track: str
    active_routes: tuple[str, ...]
    keyword_limit: int
    category_limit: int
    metadata_limit: int
    dense_limit: int
    hard_filtering: bool
    dense_mode: str
    diversity_enabled: bool
    diversity_strength: float
    profile_weight: float
    semantic_ranker_enabled: bool
    semantic_ranker_top_n: int
    clarification_mode: str
    novelty_penalty: float
    fallback_policy: str
    context_revision: int
    reasons: tuple[str, ...]

    def routing(self, base: RoutingDecision) -> RoutingDecision:
        return replace(
            base,
            track=self.track,
            hard_filtering=self.hard_filtering,
            keyword_limit=self.keyword_limit,
            category_limit=self.category_limit,
            metadata_limit=self.metadata_limit,
            dense_limit=self.dense_limit,
            dense_mode=self.dense_mode,
            diversity_enabled=self.diversity_enabled,
            reasons=tuple((*base.reasons, *self.reasons)),
        )


@dataclass(frozen=True)
class StrategyOutcome:
    turn: int
    context_revision: int
    program_track: str
    candidate_counts: tuple[tuple[str, int], ...]
    unique_candidate_count: int
    candidate_reduction: int | None
    applied_constraints: tuple[str, ...]
    relaxed_constraints: tuple[str, ...]
    recommendation_repeat_rate: float
    clarification_attribute: str | None
    clarification_answered: bool
    slot_acquired: bool
    user_rejection: bool
    override_detected: bool
    llm_latency_ms: float | None
    llm_failure: bool
    fallback_used: bool


class AdaptiveOrchestrator:
    """Compile bounded per-turn plans; shared SolutionConfig is never mutated."""

    def __init__(self, config: SolutionConfig) -> None:
        self.config = config

    def pre_retrieval(self, context: DistilledContext, base: RoutingDecision) -> ContextProgram:
        reasons = [f"base_{base.track}"]
        profile_weight = float(self.config.reranker_weights.get("profile", 0.0))
        if context.profile_conflict_attributes:
            profile_weight = 0.0
            reasons.append("current_request_overrides_profile")
        novelty = 0.0
        diversity = base.diversity_enabled
        dense_limit = base.dense_limit
        dense_mode = base.dense_mode
        if context.no_progress_turns >= 2 and not context.recent_override:
            dense_limit = min(
                self.config.orchestration_max_dense_limit,
                max(base.dense_limit, self.config.browsing_dense_limit),
            )
            novelty = self.config.orchestration_novelty_penalty
            diversity = True
            reasons.append("no_progress_expand_and_diversify")
        if context.rejected_candidates:
            novelty = max(novelty, self.config.orchestration_novelty_penalty)
            diversity = True
            reasons.append("user_rejection_avoid_previous_candidates")
        if context.recent_override:
            reasons.append("recent_override_prioritize_current_slots")
        semantic_enabled = self.config.semantic_ranker_enabled
        if context.consecutive_llm_failures >= self.config.semantic_ranker_circuit_breaker_failures:
            semantic_enabled = False
            reasons.append("session_llm_circuit_open")
        return ContextProgram(
            track=base.track,
            active_routes=("bm25", "category", "metadata", "dense"),
            keyword_limit=min(base.keyword_limit, self.config.orchestration_max_sparse_limit),
            category_limit=min(base.category_limit, self.config.orchestration_max_sparse_limit),
            metadata_limit=min(base.metadata_limit, self.config.orchestration_max_sparse_limit),
            dense_limit=min(dense_limit, self.config.orchestration_max_dense_limit),
            hard_filtering=base.hard_filtering,
            dense_mode=dense_mode,
            diversity_enabled=diversity,
            diversity_strength=min(
                self.config.orchestration_max_diversity_strength,
                self.config.browsing_diversity_strength,
            ),
            profile_weight=profile_weight,
            semantic_ranker_enabled=semantic_enabled,
            semantic_ranker_top_n=min(
                self.config.semantic_ranker_top_n,
                self.config.orchestration_max_semantic_top_n,
            ),
            clarification_mode="information_gain",
            novelty_penalty=novelty,
            fallback_policy="deterministic_ranker",
            context_revision=context.context_revision,
            reasons=tuple(reasons),
        )

    def post_probe(
        self,
        program: ContextProgram,
        unique_candidate_count: int,
        saturated_routes: tuple[str, ...],
        overloaded: bool,
    ) -> ContextProgram:
        reasons = list(program.reasons)
        if overloaded:
            reasons.append("probe_overload_cutoff")
            return replace(
                program,
                active_routes=("bm25", "category", "metadata"),
                dense_limit=0,
                semantic_ranker_enabled=False,
                clarification_mode="proactive_cutoff",
                reasons=tuple(reasons),
            )
        if unique_candidate_count < self.config.orchestration_low_candidate_threshold:
            reasons.append("probe_low_candidates_expand_dense")
            return replace(
                program,
                dense_limit=self.config.orchestration_max_dense_limit,
                dense_mode="semantic_pool",
                reasons=tuple(reasons),
            )
        if len(saturated_routes) >= 2:
            reasons.append("probe_sparse_saturation_keep_dense_pool")
        return replace(program, reasons=tuple(reasons))


def apply_novelty_penalty(
    candidates: list[Candidate],
    previous_ids: tuple[str, ...] | list[str],
    penalty: float,
) -> list[Candidate]:
    if penalty <= 0.0 or not previous_ids:
        return candidates
    previous = set(previous_ids)
    for candidate in candidates:
        if candidate.parent_asin in previous:
            candidate.score -= penalty
    return sorted(candidates, key=lambda item: (-item.score, item.parent_asin))
