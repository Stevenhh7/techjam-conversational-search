from __future__ import annotations

from dataclasses import dataclass

from solution.config import SolutionConfig
from solution.query_builder import BuiltQuery
from solution.ranking.constraints import apply_precision_constraints
from solution.ranking.diversity import diversify_categories, is_open_category
from solution.ranking.reranker import rerank
from solution.retrieval.base import Candidate
from solution.retrieval.bm25 import BM25Retriever
from solution.retrieval.category import CategoryRetriever
from solution.retrieval.dense import DenseRetriever
from solution.retrieval.fusion import attach_route_evidence, reciprocal_rank_fusion, supplement_with_dense
from solution.schemas import RoutingDecision, SessionState


@dataclass(frozen=True)
class PipelineResult:
    routes: dict[str, list[Candidate]]
    sparse_fused: list[Candidate]
    fused: list[Candidate]
    ranked: list[Candidate]
    applied_constraints: tuple[str, ...]
    relaxed_constraints: tuple[str, ...]
    diversity_applied: bool


@dataclass(frozen=True)
class ProbeResult:
    routes: dict[str, list[Candidate]]
    sparse_fused: list[Candidate]
    unique_candidate_count: int
    saturated_routes: tuple[str, ...]


class HybridPipeline:
    """Intent-aware in-memory keyword/category/vector retrieval pipeline."""

    def __init__(
        self,
        bm25: BM25Retriever,
        category: CategoryRetriever,
        dense: DenseRetriever,
        products: dict[str, dict],
        config: SolutionConfig,
    ) -> None:
        self.bm25 = bm25
        self.category = category
        self.dense = dense
        self.products = products
        self.config = config

    def probe(
        self,
        query: BuiltQuery,
        decision: RoutingDecision,
    ) -> ProbeResult:
        routes = {
            "bm25": self.bm25.search(query.lexical, decision.keyword_limit),
            "category": self.category.search(query.category, decision.category_limit),
            "metadata": self.bm25.metadata_search(query.lexical, decision.metadata_limit),
        }
        weights = (
            self.config.buying_weights
            if decision.track == "precision"
            else self.config.browsing_weights
        )
        if decision.track == "precision":
            sparse_fused = reciprocal_rank_fusion(
                {name: routes[name] for name in ("bm25", "metadata")},
                weights,
                self.config.rrf_k,
            )
            sparse_fused = attach_route_evidence(
                sparse_fused,
                routes["category"],
                "category",
            )
        else:
            sparse_fused = reciprocal_rank_fusion(
                {name: routes[name] for name in ("bm25", "category", "metadata")},
                weights,
                self.config.rrf_k,
            )
        identifiers = {
            item.parent_asin
            for candidates in routes.values()
            for item in candidates
        }
        limits = {
            "bm25": decision.keyword_limit,
            "category": decision.category_limit,
            "metadata": decision.metadata_limit,
        }
        saturated = tuple(
            name
            for name in ("bm25", "category", "metadata")
            if limits[name] > 0 and len(routes[name]) >= limits[name]
        )
        return ProbeResult(
            routes=routes,
            sparse_fused=sparse_fused,
            unique_candidate_count=len(identifiers),
            saturated_routes=saturated,
        )

    def run(
        self,
        query: BuiltQuery,
        state: SessionState,
        decision: RoutingDecision,
        probe: ProbeResult | None = None,
        reranker_weights: dict[str, float] | None = None,
        diversity_strength: float | None = None,
    ) -> PipelineResult:
        probe = probe or self.probe(query, decision)
        routes = {
            **probe.routes,
            "dense": self.dense.search(query.semantic, decision.dense_limit),
        }
        weights = (
            self.config.buying_weights
            if decision.track == "precision"
            else self.config.browsing_weights
        )
        sparse_fused = probe.sparse_fused
        if decision.dense_mode == "rrf":
            fused = reciprocal_rank_fusion(routes, weights, self.config.rrf_k)
        else:
            dense_limit = (
                self.config.dense_supplement_limit
                if decision.track == "precision"
                else decision.dense_limit
            )
            fused = supplement_with_dense(
                sparse_fused,
                routes["dense"],
                self.config.dense_supplement_weight,
                self.config.rrf_k,
                dense_limit,
            )

        applied: tuple[str, ...] = ()
        relaxed: tuple[str, ...] = ()
        filtered = fused
        if decision.hard_filtering:
            filtered, applied, relaxed = apply_precision_constraints(
                fused,
                self.products,
                state,
                self.config.buying_min_filtered_candidates,
            )
        ranked = rerank(
            filtered,
            self.products,
            query,
            state,
            reranker_weights or self.config.reranker_weights,
        )
        diversity_applied = bool(
            decision.diversity_enabled and is_open_category(state.category)
        )
        if diversity_applied:
            ranked = diversify_categories(
                ranked,
                self.products,
                self.config.browsing_diversity_strength
                if diversity_strength is None
                else diversity_strength,
            )
        return PipelineResult(
            routes=routes,
            sparse_fused=sparse_fused,
            fused=fused,
            ranked=ranked,
            applied_constraints=applied,
            relaxed_constraints=relaxed,
            diversity_applied=diversity_applied,
        )

    def provisional(
        self,
        query: BuiltQuery,
        state: SessionState,
        decision: RoutingDecision,
        probe: ProbeResult,
        reranker_weights: dict[str, float] | None = None,
        diversity_strength: float | None = None,
    ) -> PipelineResult:
        fused = list(probe.sparse_fused)
        ranked = rerank(
            fused,
            self.products,
            query,
            state,
            reranker_weights or self.config.reranker_weights,
        )
        diversity_applied = bool(
            decision.diversity_enabled and is_open_category(state.category)
        )
        if diversity_applied:
            ranked = diversify_categories(
                ranked,
                self.products,
                self.config.browsing_diversity_strength
                if diversity_strength is None
                else diversity_strength,
            )
        return PipelineResult(
            routes={**probe.routes, "dense": []},
            sparse_fused=probe.sparse_fused,
            fused=fused,
            ranked=ranked,
            applied_constraints=(),
            relaxed_constraints=(),
            diversity_applied=diversity_applied,
        )
