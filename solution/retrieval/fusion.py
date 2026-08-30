from __future__ import annotations

from solution.retrieval.base import Candidate


def reciprocal_rank_fusion(
    routes: dict[str, list[Candidate]], weights: dict[str, float], k: int = 60
) -> list[Candidate]:
    fused: dict[str, Candidate] = {}
    for route, candidates in routes.items():
        weight = weights.get(route, 0.0)
        for rank, candidate in enumerate(candidates, 1):
            item = fused.setdefault(candidate.parent_asin, Candidate(candidate.parent_asin, 0.0))
            item.score += weight / (k + rank)
            item.route_ranks[route] = rank
            item.route_scores[route] = candidate.score
    return sorted(fused.values(), key=lambda item: (-item.score, item.parent_asin))

