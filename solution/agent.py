from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

from solution.catalog import load_documents
from solution.clarification import ALLOWED_ATTRIBUTES, choose_clarification
from solution.config import SolutionConfig
from solution.context.distiller import ContextDistiller
from solution.context.policies import profile_mutations, user_rejected
from solution.context.profile_store import InMemoryProfileStore, ProfileStore
from solution.context.schemas import LongTermProfile
from solution.generality import assess_over_generality
from solution.llm.base import SemanticRankResult, SemanticRanker
from solution.llm.factory import create_semantic_ranker
from solution.orchestration import AdaptiveOrchestrator, StrategyOutcome, apply_novelty_penalty
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
        profile_store: ProfileStore | None = None,
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
        self.semantic_ranker_explicit = semantic_ranker is not None
        self.semantic_ranker = semantic_ranker or create_semantic_ranker(self.config)
        self.profile_store = profile_store or InMemoryProfileStore(
            self.config.profile_promotion_sessions,
            self.config.profile_confidence_decay,
        )
        self.context_distiller = ContextDistiller(
            self.config.context_max_messages,
            self.config.context_max_candidates,
            self.config.context_max_preferences,
            self.config.context_max_summary_chars,
            self.config.context_max_outcomes,
        )
        self.orchestrator = AdaptiveOrchestrator(self.config)
        self.pipeline = HybridPipeline(
            self.bm25,
            self.category,
            self.dense,
            self.products,
            self.config,
        )
        self.sessions: dict[str, SessionState] = {}
        self.response_cache: dict[str, dict[int, tuple[str, int, dict]]] = {}
        self.profile_snapshots: dict[str, LongTermProfile] = {}
        self.popular = sorted(
            self.documents,
            key=lambda doc: (-(doc.raw.get("rating_number") or 0), doc.parent_asin),
        )

    def reset(self, session_id: str, user_profile: dict) -> None:
        supplied = dict(user_profile or {})
        profile_id = str(supplied.get("profile_id", "")).strip()[:128] or None
        self.sessions[session_id] = SessionState(
            session_id=session_id,
            user_profile=supplied,
            profile_id=profile_id,
        )
        self.profile_snapshots[session_id] = (
            self.profile_store.load(profile_id) if profile_id else LongTermProfile("")
        )
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
        state = self.sessions[session_id]
        previous_ids = tuple(state.previous_recommendations)
        previous_pending = state.pending_clarification
        previous_slots = {
            (item.attribute, item.value) for item in state.structured_constraints
        }
        state = update_state(state, user_message, turn)
        rejected = user_rejected(user_message)
        if rejected:
            for parent_asin in previous_ids:
                if parent_asin not in state.rejected_recommendations:
                    state.rejected_recommendations.append(parent_asin)
        if state.profile_id:
            mutations = profile_mutations(state, user_message)
            if mutations:
                self.profile_snapshots[session_id] = self.profile_store.update(
                    state.profile_id,
                    mutations,
                )
        profile = self.profile_snapshots.get(session_id, LongTermProfile(""))
        context = self.context_distiller.distill(state, profile)
        state.distilled_context = context
        query = build_query(state)
        base_routing = route_intent(state, self.config)
        program = self.orchestrator.pre_retrieval(context, base_routing)
        if (
            self.semantic_ranker_explicit
            and context.consecutive_llm_failures
            < self.config.semantic_ranker_circuit_breaker_failures
        ):
            program = replace(
                program,
                semantic_ranker_enabled=True,
                reasons=tuple((*program.reasons, "explicit_ranker_enabled")),
            )
        routing = program.routing(base_routing)
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
        program = self.orchestrator.post_probe(
            program,
            probe.unique_candidate_count,
            probe.saturated_routes,
            generality.overloaded,
        )
        routing = program.routing(base_routing)
        state.last_routing = routing
        state.context_program = program
        reranker_weights = dict(self.config.reranker_weights)
        reranker_weights["profile"] = program.profile_weight
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
            pipeline_result = self.pipeline.provisional(
                query,
                state,
                routing,
                probe,
                reranker_weights,
                program.diversity_strength,
            )
            ranked = pipeline_result.ranked
            semantic_result = SemanticRankResult(
                ordered_parent_asins=tuple(item.parent_asin for item in ranked),
                applied=False,
                reason="over_generality_cutoff",
            )
        else:
            transition_state(state, "ready", turn, "full_retrieval_authorized")
            pipeline_result = self.pipeline.run(
                query,
                state,
                routing,
                probe,
                reranker_weights,
                program.diversity_strength,
            )
            ranked = self.cross_encoder.rerank(
                pipeline_result.ranked,
                query.semantic,
                self.products,
            )
            if program.semantic_ranker_enabled:
                ranked, semantic_result = semantic_rerank(
                    ranked,
                    self.products,
                    query.semantic,
                    state,
                    routing,
                    self.semantic_ranker,
                    program.semantic_ranker_top_n,
                )
            else:
                semantic_result = SemanticRankResult(
                    ordered_parent_asins=tuple(item.parent_asin for item in ranked),
                    applied=False,
                    reason="context_program_disabled",
                )
            ranked = apply_novelty_penalty(
                ranked,
                previous_ids,
                program.novelty_penalty,
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
        current_slots = {(item.attribute, item.value) for item in state.structured_constraints}
        clarification_answered = bool(
            previous_pending
            and previous_pending.attribute
            and (
                previous_pending.attribute in state.slot_store
                or previous_pending.attribute in state.unavailable_attributes
                or (previous_pending.attribute == "category" and state.category)
            )
        )
        repeated = len(set(previous_ids) & set(recommendations))
        repeat_rate = repeated / max(1, len(recommendations)) if previous_ids else 0.0
        semantic_status = self.semantic_ranker.status()
        semantic_expected = program.semantic_ranker_enabled and not cutoff
        llm_failure = bool(
            semantic_expected
            and not semantic_result.applied
            and semantic_result.reason not in {"no candidates", "ollama_qwen_no_candidates"}
        )
        outcome = StrategyOutcome(
            turn=turn,
            context_revision=context.context_revision,
            program_track=program.track,
            candidate_counts=tuple(
                sorted((name, len(values)) for name, values in pipeline_result.routes.items())
            ),
            unique_candidate_count=probe.unique_candidate_count,
            candidate_reduction=(
                state.strategy_outcomes[-1].unique_candidate_count - probe.unique_candidate_count
                if state.strategy_outcomes
                else None
            ),
            applied_constraints=pipeline_result.applied_constraints,
            relaxed_constraints=pipeline_result.relaxed_constraints,
            recommendation_repeat_rate=round(repeat_rate, 6),
            clarification_attribute=attribute,
            clarification_answered=clarification_answered,
            slot_acquired=bool(current_slots - previous_slots),
            user_rejection=rejected,
            override_detected=state.last_override_turn == turn,
            llm_latency_ms=(
                float(semantic_status["last_latency_ms"])
                if semantic_expected and semantic_status.get("last_latency_ms") is not None
                else None
            ),
            llm_failure=llm_failure,
            fallback_used=bool(llm_failure or pipeline_result.relaxed_constraints),
        )
        state.strategy_outcomes.append(outcome)
        state.strategy_outcomes = state.strategy_outcomes[-max(4, self.config.context_max_outcomes * 2):]
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
                    "distilled_context": {
                        "core_goal": context.core_goal,
                        "intent": context.intent,
                        "confirmed_preferences": [
                            f"{item.attribute}:{item.value}" for item in context.confirmed_preferences
                        ],
                        "tentative_preferences": [
                            f"{item.attribute}:{item.value}" for item in context.tentative_preferences
                        ],
                        "negative_preferences": [item.value for item in context.negative_preferences],
                        "long_term_preferences": [
                            f"{item.attribute}:{item.value}" for item in context.long_term_preferences
                        ],
                        "profile_conflict_attributes": list(context.profile_conflict_attributes),
                        "no_progress_turns": context.no_progress_turns,
                        "consecutive_llm_failures": context.consecutive_llm_failures,
                        "summary": context.summary,
                        "context_revision": context.context_revision,
                    },
                    "context_program": {
                        "track": program.track,
                        "active_routes": list(program.active_routes),
                        "route_limits": {
                            "bm25": program.keyword_limit,
                            "category": program.category_limit,
                            "metadata": program.metadata_limit,
                            "dense": program.dense_limit,
                        },
                        "hard_filtering": program.hard_filtering,
                        "dense_mode": program.dense_mode,
                        "diversity_enabled": program.diversity_enabled,
                        "diversity_strength": program.diversity_strength,
                        "profile_weight": program.profile_weight,
                        "semantic_ranker_enabled": program.semantic_ranker_enabled,
                        "semantic_ranker_top_n": program.semantic_ranker_top_n,
                        "clarification_mode": program.clarification_mode,
                        "novelty_penalty": program.novelty_penalty,
                        "fallback_policy": program.fallback_policy,
                        "context_revision": program.context_revision,
                        "reasons": list(program.reasons),
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
                    "strategy_outcome": {
                        "candidate_counts": dict(outcome.candidate_counts),
                        "unique_candidate_count": outcome.unique_candidate_count,
                        "candidate_reduction": outcome.candidate_reduction,
                        "recommendation_repeat_rate": outcome.recommendation_repeat_rate,
                        "clarification_answered": outcome.clarification_answered,
                        "slot_acquired": outcome.slot_acquired,
                        "user_rejection": outcome.user_rejection,
                        "override_detected": outcome.override_detected,
                        "llm_latency_ms": outcome.llm_latency_ms,
                        "llm_failure": outcome.llm_failure,
                        "fallback_used": outcome.fallback_used,
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
