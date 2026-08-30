from __future__ import annotations

from solution.catalog import exact_attributes, flatten, leaf_category
from solution.llm.base import SemanticRankRequest, SemanticRankResult, SemanticRanker
from solution.retrieval.base import Candidate
from solution.schemas import RoutingDecision, SemanticCandidate, SessionState


def _fallback_result(candidates: list[Candidate], reason: str) -> SemanticRankResult:
    return SemanticRankResult(
        ordered_parent_asins=tuple(item.parent_asin for item in candidates),
        applied=False,
        reason=reason,
    )


def semantic_rerank(
    candidates: list[Candidate],
    products: dict[str, dict],
    query: str,
    state: SessionState,
    routing: RoutingDecision,
    ranker: SemanticRanker,
    top_n: int,
) -> tuple[list[Candidate], SemanticRankResult]:
    count = min(max(0, top_n), len(candidates))
    if count == 0:
        result = _fallback_result(candidates, "no candidates")
        return candidates, result
    head = candidates[:count]
    request = SemanticRankRequest(
        query=query,
        routing=routing,
        constraints=tuple(state.structured_constraints),
        profile_summary=str(state.user_profile.get("summary", ""))[:240],
        candidates=tuple(
            SemanticCandidate(
                parent_asin=item.parent_asin,
                title=flatten(products[item.parent_asin].get("title"))[:200],
                category=leaf_category(products[item.parent_asin])[:100],
                attributes=exact_attributes(products[item.parent_asin])[:180],
                deterministic_score=float(item.score),
                route_ranks=tuple(sorted(item.route_ranks.items())),
            )
            for item in head
        ),
    )
    try:
        result = ranker.rank(request)
    except Exception as exc:
        return candidates, _fallback_result(candidates, f"semantic ranker failed: {type(exc).__name__}")
    if not isinstance(result, SemanticRankResult):
        return candidates, _fallback_result(candidates, "semantic ranker returned an invalid result type")
    if not result.applied:
        return candidates, result
    expected = {item.parent_asin for item in head}
    ordered = result.ordered_parent_asins
    if len(ordered) != len(expected) or len(set(ordered)) != len(ordered) or set(ordered) != expected:
        return candidates, _fallback_result(candidates, "semantic ranker returned an invalid candidate permutation")
    by_id = {item.parent_asin: item for item in head}
    return [*(by_id[parent_asin] for parent_asin in ordered), *candidates[count:]], result
