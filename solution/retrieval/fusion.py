from __future__ import annotations

from solution.retrieval.base import Candidate


def reciprocal_rank_fusion(
    routes: dict[str, list[Candidate]], weights: dict[str, float], k: int = 60
) -> list[Candidate]:
    fused: dict[str, Candidate] = {}
    for route, candidates in routes.items():
        weight = weights.get(route, 0.0)
        if weight <= 0.0:
            continue
        for rank, candidate in enumerate(candidates, 1):
            item = fused.setdefault(candidate.parent_asin, Candidate(candidate.parent_asin, 0.0))
            item.score += weight / (k + rank)
            item.route_ranks[route] = rank
            item.route_scores[route] = candidate.score
    return sorted(fused.values(), key=lambda item: (-item.score, item.parent_asin))


def attach_route_evidence(
    candidates: list[Candidate],
    route_candidates: list[Candidate],
    route: str,
) -> list[Candidate]:
    """Attach an audit route without changing recall membership or fused scores."""

    by_id = {item.parent_asin: item for item in candidates}
    for rank, evidence in enumerate(route_candidates, 1):
        item = by_id.get(evidence.parent_asin)
        if item is None:
            continue
        item.route_ranks[route] = rank
        item.route_scores[route] = evidence.score
    return candidates


def supplement_with_dense(
    sparse_candidates: list[Candidate],
    dense_candidates: list[Candidate],
    weight: float,
    k: int = 60,
    limit: int = 60,
) -> list[Candidate]:
    """Attach dense evidence and add dense-only candidates without reordering sparse hits.

    Dense scores remain available to the reranker, but a product already recalled by
    BM25/metadata keeps its sparse RRF score. This prevents the dense route from
    receiving both an RRF boost and a second large reranker boost.
    """

    fused = {item.parent_asin: item for item in sparse_candidates}
    dense_floor = min((item.score for item in sparse_candidates), default=0.0)
    for rank, dense in enumerate(dense_candidates[:limit], 1):
        item = fused.get(dense.parent_asin)
        if item is None:
            # Keep dense-only candidates below the sparse tail. Lexical/exact
            # reranker evidence can still promote a genuinely useful supplement.
            item = Candidate(dense.parent_asin, min(dense_floor, weight / (k + rank)))
            fused[dense.parent_asin] = item
        item.route_ranks["dense"] = rank
        item.route_scores["dense"] = dense.score
    return sorted(fused.values(), key=lambda item: (-item.score, item.parent_asin))
