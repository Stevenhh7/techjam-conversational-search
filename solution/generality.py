from __future__ import annotations

from solution.config import SolutionConfig
from solution.pipeline import ProbeResult
from solution.query_builder import BuiltQuery
from solution.ranking.diversity import is_open_category
from solution.retrieval.bm25 import query_terms
from solution.schemas import OverGeneralityDecision, RoutingDecision, SessionState


def assess_over_generality(
    state: SessionState,
    query: BuiltQuery,
    routing: RoutingDecision,
    probe: ProbeResult,
    config: SolutionConfig,
) -> OverGeneralityDecision:
    active_slots = sum(len(values) for values in state.slot_store.values())
    term_count = len(query_terms(query.lexical))
    saturated = probe.saturated_routes
    reasons: list[str] = []

    if not config.over_generality_cutoff_enabled:
        reasons.append("cutoff_disabled")
    if routing.track != "discovery":
        reasons.append("precision_track")
    if not is_open_category(state.category):
        reasons.append("specific_category_present")
    if active_slots > config.over_generality_max_active_slots:
        reasons.append("confirmed_slots_available")

    vague_query = term_count <= config.over_generality_max_query_terms
    candidate_overload = probe.unique_candidate_count >= config.over_generality_min_unique_candidates
    route_overload = len(saturated) >= config.over_generality_min_saturated_routes
    if vague_query:
        reasons.append("low_query_specificity")
    if candidate_overload:
        reasons.append("candidate_pool_overload")
    if route_overload:
        reasons.append("multiple_sparse_routes_saturated")
    if not query.lexical.strip():
        reasons.append("empty_catalog_query")

    eligible = (
        config.over_generality_cutoff_enabled
        and routing.track == "discovery"
        and is_open_category(state.category)
        and active_slots <= config.over_generality_max_active_slots
    )
    overloaded = eligible and (vague_query or candidate_overload or route_overload)
    if not overloaded:
        confidence = 0.0
    elif not query.lexical.strip():
        confidence = 0.98
    elif route_overload or candidate_overload:
        confidence = 0.90
    else:
        confidence = 0.78
    return OverGeneralityDecision(
        overloaded=overloaded,
        confidence=confidence,
        reasons=tuple(reasons),
        unique_candidate_count=probe.unique_candidate_count,
        saturated_routes=saturated,
        query_term_count=term_count,
        active_slot_count=active_slots,
    )
