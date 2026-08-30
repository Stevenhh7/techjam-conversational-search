from __future__ import annotations

import copy
from pathlib import Path

from solution.catalog import load_documents
from solution.clarification import ALLOWED_ATTRIBUTES, choose_clarification
from solution.config import SolutionConfig
from solution.generality import assess_over_generality
from solution.llm.base import SemanticRankResult, SemanticRanker
from solution.llm.factory import create_semantic_ranker
from solution.pipeline import HybridPipeline
from solution.query_builder import build_query
from solution.ranking.cross_encoder import OptionalCrossEncoder
from solution.ranking.semantic import semantic_rerank
from solution.retrieval.bm25 import BM25Retriever
from solution.retrieval.category import CategoryRetriever
from solution.retrieval.dense import DenseRetriever
from solution.routing import route_intent
from solution.schemas import ClarificationDecision, SessionState
from solution.state import update_state
from solution.state_machine import transition_state


class Agent:
    """Deterministic hybrid agent compatible with the official API contract."""

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        config: SolutionConfig | None = None,
        diagnostics: bool = False,
        semantic_ranker: SemanticRanker | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.config = config or SolutionConfig()
        self.diagnostics = diagnostics
        self.traces: dict[str, list[dict]] = {}
        repository_root = self.catalog_path.resolve().parent.parent
        embeddings_path = self.config.dense_embeddings_path
        metadata_path = self.config.dense_metadata_path
        cache_dir = self.config.dense_cache_dir
        if not embeddings_path.is_absolute():
            embeddings_path = repository_root / embeddings_path
        if not metadata_path.is_absolute():
            metadata_path = repository_root / metadata_path
        if not cache_dir.is_absolute():
            cache_dir = repository_root / cache_dir
        self.documents = load_documents(self.catalog_path)
        self.products = {doc.parent_asin: doc.raw for doc in self.documents}
        self.bm25 = BM25Retriever(self.documents)
        self.category = CategoryRetriever(self.documents)
        self.dense = DenseRetriever(
            embeddings_path,
            metadata_path,
            self.config.dense_model,
            self.catalog_path,
            expected_count=len(self.documents),
            providers=self.config.dense_providers,
            cache_dir=cache_dir,
        )
        self.cross_encoder = OptionalCrossEncoder(
            self.config.cross_encoder_enabled,
            self.config.cross_encoder_model,
            self.config.cross_encoder_top_n,
            self.config.cross_encoder_weight,
            self.config.cross_encoder_latency_budget_ms,
        )
        self.semantic_ranker = semantic_ranker or create_semantic_ranker(self.config)
        self.pipeline = HybridPipeline(
            self.bm25,
            self.category,
            self.dense,
            self.products,
            self.config,
        )
        self.sessions: dict[str, SessionState] = {}
        self.response_cache: dict[str, dict[int, tuple[str, int, dict]]] = {}
        self.popular = sorted(
            self.documents,
            key=lambda doc: (-(doc.raw.get("rating_number") or 0), doc.parent_asin),
        )

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.sessions[session_id] = SessionState(session_id=session_id, user_profile=user_profile or {})
        self.response_cache[session_id] = {}
        if self.diagnostics:
            self.traces[session_id] = []

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before respond")
        cached = self.response_cache.setdefault(session_id, {}).get(turn)
        if cached is not None:
            cached_message, cached_top_k, cached_response = cached
            if cached_message != user_message or cached_top_k != top_k:
                raise RuntimeError("the same turn cannot be replayed with different input")
            return copy.deepcopy(cached_response)
        state = update_state(self.sessions[session_id], user_message, turn)
        query = build_query(state)
        routing = route_intent(state, self.config)
        state.last_routing = routing
        probe = self.pipeline.probe(query, routing)
        generality = assess_over_generality(
            state,
            query,
            routing,
            probe,
            self.config,
        )
        state.over_generality = generality
        blocked = state.asked_attributes | state.unavailable_attributes
        if state.category:
            blocked.add("category")
        can_clarify = any(attribute not in blocked for attribute in ALLOWED_ATTRIBUTES)
        cutoff = bool(
            generality.overloaded
            and can_clarify
            and turn <= self.config.over_generality_ask_until_turn
        )
        if cutoff:
            transition_state(state, "overloaded", turn, "over_generality_cutoff")
            pipeline_result = self.pipeline.provisional(query, state, routing, probe)
            ranked = pipeline_result.ranked
            semantic_result = SemanticRankResult(
                ordered_parent_asins=tuple(item.parent_asin for item in ranked),
                applied=False,
                reason="over_generality_cutoff",
            )
        else:
            transition_state(state, "ready", turn, "full_retrieval_authorized")
            pipeline_result = self.pipeline.run(query, state, routing, probe)
            ranked = self.cross_encoder.rerank(
                pipeline_result.ranked,
                query.semantic,
                self.products,
            )
            ranked, semantic_result = semantic_rerank(
                ranked,
                self.products,
                query.semantic,
                state,
                routing,
                self.semantic_ranker,
                self.config.semantic_ranker_top_n,
            )
        ranked_ids = [item.parent_asin for item in ranked]
        if len(ranked_ids) < top_k:
            seen = set(ranked_ids)
            ranked_ids.extend(doc.parent_asin for doc in self.popular if doc.parent_asin not in seen)
        recommendations = ranked_ids[:top_k]
        should_ask = cutoff or turn <= self.config.ask_until_turn
        if should_ask:
            clarification = choose_clarification(
                state,
                ranked_ids,
                self.products,
                proactive=cutoff,
                allow_late=cutoff,
            )
        else:
            clarification = ClarificationDecision(
                None,
                0.0,
                "question_window_closed",
                0.0,
                0.0,
                0.0,
                (),
                None,
            )
        attribute = clarification.attribute
        if attribute:
            state.asked_attributes.add(attribute)
            transition_state(
                state,
                "clarifying",
                turn,
                "proactive_overload_guidance" if cutoff else "candidate_information_gain",
            )
        state.pending_clarification = clarification
        state.previous_recommendations = recommendations
        if self.diagnostics:
            self.traces[session_id].append(
                {
                    "turn": turn,
                    "user_message": user_message,
                    "intent": state.intent,
                    "buying_probability": state.buying_probability,
                    "routing": {
                        "intent": routing.intent,
                        "confidence": routing.confidence,
                        "track": routing.track,
                        "category_strictness": routing.category_strictness,
                        "dense_mode": routing.dense_mode,
                        "reasons": list(routing.reasons),
                    },
                    "query": {
                        "lexical": query.lexical,
                        "semantic": query.semantic,
                        "category": query.category,
                        "profile": query.profile,
                    },
                    "state": {
                        "hard_constraints": list(state.hard_constraints),
                        "soft_preferences": list(state.soft_preferences),
                        "exclusions": sorted(state.exclusions),
                        "structured_constraints": [
                            {
                                "attribute": item.attribute,
                                "operator": item.operator,
                                "value": item.value,
                                "confidence": item.confidence,
                                "source_turn": item.source_turn,
                                "hard": item.hard,
                            }
                            for item in state.structured_constraints
                        ],
                        "slot_store": {
                            name: [item.value for item in values]
                            for name, values in sorted(state.slot_store.items())
                        },
                        "dialogue_phase": state.dialogue_phase,
                        "state_revision": state.state_revision,
                    },
                    "probe": {
                        "unique_candidate_count": probe.unique_candidate_count,
                        "saturated_routes": list(probe.saturated_routes),
                    },
                    "over_generality": {
                        "overloaded": generality.overloaded,
                        "confidence": generality.confidence,
                        "reasons": list(generality.reasons),
                        "query_term_count": generality.query_term_count,
                        "active_slot_count": generality.active_slot_count,
                    },
                    "retrieval_cutoff": cutoff,
                    "routes": {
                        name: [item.parent_asin for item in candidates]
                        for name, candidates in pipeline_result.routes.items()
                    },
                    "sparse_fused": [item.parent_asin for item in pipeline_result.sparse_fused],
                    "fused": [item.parent_asin for item in pipeline_result.fused],
                    "final": ranked_ids,
                    "applied_constraints": list(pipeline_result.applied_constraints),
                    "relaxed_constraints": list(pipeline_result.relaxed_constraints),
                    "diversity_applied": pipeline_result.diversity_applied,
                    "ask_attribute": attribute,
                    "clarification": {
                        "reason": clarification.reason,
                        "score": clarification.score,
                        "coverage": clarification.coverage,
                        "entropy": clarification.entropy,
                        "expected_reduction": clarification.expected_reduction,
                        "example_values": list(clarification.example_values),
                    },
                    "cross_encoder": self.cross_encoder.status(),
                    "semantic_ranker": {
                        **self.semantic_ranker.status(),
                        "applied": semantic_result.applied,
                        "reason": semantic_result.reason,
                    },
                }
            )
        if cutoff and clarification.prompt:
            message = clarification.prompt
        else:
            message = "Here are the strongest current matches."
            if clarification.prompt:
                message += " " + clarification.prompt
        response = {
            "message": message,
            "ask_attribute": attribute,
            "recommendations": [{"parent_asin": value} for value in recommendations],
            "usage": {
                "prompt_tokens": max(0, semantic_result.prompt_tokens),
                "completion_tokens": max(0, semantic_result.completion_tokens),
            },
        }
        self.response_cache[session_id][turn] = (
            user_message,
            top_k,
            copy.deepcopy(response),
        )
        return response

    def get_trace(self, session_id: str) -> tuple[dict, ...]:
        """Return immutable diagnostic snapshots; empty when diagnostics are off."""

        return tuple(self.traces.get(session_id, ()))

    def close(self) -> None:
        if getattr(self, "bm25", None) is not None:
            self.bm25.close()
        close = getattr(getattr(self, "semantic_ranker", None), "close", None)
        if callable(close):
            close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
