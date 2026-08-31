from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from solution.agent import Agent
from solution.config import SolutionConfig
from solution.context.distiller import ContextDistiller
from solution.context.policies import profile_mutations
from solution.context.profile_store import InMemoryProfileStore
from solution.context.schemas import LongTermProfile, PreferenceEvidence, ProfileMutation
from solution.llm.base import SemanticRankRequest, SemanticRankResult
from solution.llm.qwen import OllamaQwenSemanticRanker
from solution.orchestration import AdaptiveOrchestrator
from solution.routing import route_intent
from solution.schemas import Constraint, SemanticCandidate, SessionState


def evidence(attribute: str, value: str, confidence: float = 0.9) -> PreferenceEvidence:
    return PreferenceEvidence(
        attribute=attribute,
        value=value,
        polarity="positive",
        explicit=True,
        confidence=confidence,
        source_turn=1,
        source_session="older-session",
        session_only=False,
        durable=True,
        updated_revision=1,
        confirmations=2,
    )


class ContextProgrammingTests(unittest.TestCase):
    def test_distilled_context_is_bounded_deterministic_and_detects_profile_conflict(self) -> None:
        state = SessionState(
            "session",
            {"summary": "likes durable products"},
            turn=3,
            intent="buying",
            buying_probability=0.9,
            category="boots",
            structured_constraints=[
                Constraint("color", "contains", "blue", 0.96, 3, True, "blue")
            ],
            previous_recommendations=[f"A{index}" for index in range(20)],
            message_history=[f"message {index}" for index in range(10)],
            state_revision=3,
        )
        profile = LongTermProfile(
            "user",
            preferences=(evidence("color", "red"), evidence("material", "leather")),
            revision=2,
        )
        distiller = ContextDistiller(
            max_messages=3,
            max_candidates=5,
            max_preferences=4,
            max_summary_chars=180,
            max_outcomes=2,
        )

        first = distiller.distill(state, profile)
        second = distiller.distill(state, profile)

        self.assertEqual(first, second)
        self.assertEqual(first.profile_conflict_attributes, ("color",))
        self.assertEqual(len(first.recent_messages), 3)
        self.assertEqual(len(first.recommended_candidates), 5)
        self.assertLessEqual(len(first.summary), 180)
        self.assertEqual(first.confirmed_preferences[0].value, "blue")

    def test_profile_store_promotes_only_across_distinct_sessions_and_isolates_users(self) -> None:
        store = InMemoryProfileStore(promotion_sessions=2, decay=1.0)
        first = ProfileMutation("observe", "color", "black", 0.9, 1, "s1")
        second = ProfileMutation("observe", "color", "black", 0.9, 1, "s2")

        self.assertFalse(store.update("user-a", (first,)).preferences)
        self.assertFalse(store.update("user-a", (first,)).preferences)
        promoted = store.update("user-a", (second,))

        self.assertEqual([(item.attribute, item.value) for item in promoted.preferences], [("color", "black")])
        self.assertFalse(store.load("user-b").preferences)
        self.assertFalse(store.update("", (second,)).preferences)

    def test_profile_store_supports_explicit_remember_forget_and_decay(self) -> None:
        store = InMemoryProfileStore(promotion_sessions=2, decay=0.9)
        remembered = store.update(
            "user",
            (ProfileMutation("remember", "material", "leather", 0.95, 1, "s1"),),
        )
        self.assertTrue(remembered.preferences[0].durable)
        decayed = store.update(
            "user",
            (ProfileMutation("remember", "color", "blue", 0.9, 2, "s1"),),
        )
        leather = next(item for item in decayed.preferences if item.attribute == "material")
        self.assertLess(leather.confidence, 0.95)
        forgotten = store.update(
            "user",
            (ProfileMutation("forget", "material", "leather", 1.0, 3, "s1"),),
        )
        self.assertNotIn("material", {item.attribute for item in forgotten.preferences})
        cleared = store.update(
            "user",
            (ProfileMutation("forget", "*", "", 1.0, 4, "s1"),),
        )
        self.assertFalse(cleared.preferences)

    def test_gift_preference_is_session_only_and_never_persisted(self) -> None:
        state = SessionState(
            "s",
            {"profile_id": "user"},
            turn=1,
            structured_constraints=[
                Constraint("color", "contains", "pink", 0.96, 1, False, "pink")
            ],
        )
        self.assertEqual(profile_mutations(state, "This is a gift for my friend; remember pink."), ())

    def test_orchestrator_compiles_and_revises_bounded_programs(self) -> None:
        config = SolutionConfig(semantic_ranker_enabled=True)
        state = SessionState("s", {}, buying_probability=0.2)
        context = ContextDistiller().distill(state, LongTermProfile(""))
        context = replace(
            context,
            no_progress_turns=2,
            rejected_candidates=("A",),
            profile_conflict_attributes=("color",),
        )
        base = route_intent(state, config)
        orchestrator = AdaptiveOrchestrator(config)
        program = orchestrator.pre_retrieval(context, base)

        self.assertEqual(program.profile_weight, 0.0)
        self.assertGreater(program.novelty_penalty, 0.0)
        self.assertTrue(program.diversity_enabled)
        self.assertLessEqual(program.dense_limit, config.orchestration_max_dense_limit)

        overloaded = orchestrator.post_probe(program, 200, ("bm25", "metadata"), True)
        self.assertEqual(overloaded.dense_limit, 0)
        self.assertFalse(overloaded.semantic_ranker_enabled)
        self.assertEqual(overloaded.clarification_mode, "proactive_cutoff")

        low = orchestrator.post_probe(program, 3, (), False)
        self.assertEqual(low.dense_limit, config.orchestration_max_dense_limit)
        self.assertIn("probe_low_candidates_expand_dense", low.reasons)

        protected = orchestrator.pre_retrieval(
            replace(context, recent_override=True, rejected_candidates=()),
            base,
        )
        self.assertEqual(protected.dense_limit, base.dense_limit)
        self.assertEqual(protected.novelty_penalty, 0.0)
        self.assertIn("recent_override_prioritize_current_slots", protected.reasons)

    def test_agent_records_context_program_and_uses_rejection_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.jsonl"
            rows = [
                {"parent_asin": "A", "title": "waterproof trail shoe", "categories": ["Shoes"]},
                {"parent_asin": "B", "title": "casual blue shoe", "categories": ["Shoes"]},
                {"parent_asin": "C", "title": "winter boot", "categories": ["Boots"]},
            ]
            catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            agent = Agent(catalog, diagnostics=True)
            agent.reset("s", {})
            agent.respond("s", "I'm looking for shoes. A key requirement is: waterproof.", 1, 3)
            agent.respond("s", "None of these are what I want.", 2, 3)

            trace = agent.get_trace("s")[-1]
            self.assertIn("distilled_context", trace)
            self.assertIn("context_program", trace)
            self.assertIn("strategy_outcome", trace)
            self.assertIn("user_rejection_avoid_previous_candidates", trace["context_program"]["reasons"])
            self.assertGreater(trace["context_program"]["novelty_penalty"], 0.0)
            self.assertTrue(trace["strategy_outcome"]["user_rejection"])
            self.assertTrue(agent.sessions["s"].strategy_outcomes)
            agent.close()

    def test_profile_memory_requires_explicit_id_and_current_request_wins_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.jsonl"
            catalog.write_text(
                json.dumps({"parent_asin": "A", "title": "black blue shoe", "categories": ["Shoes"]}) + "\n",
                encoding="utf-8",
            )
            agent = Agent(catalog, diagnostics=True)
            agent.reset("remember", {"profile_id": "user-a"})
            agent.respond("remember", "Remember that I prefer black.", 1, 1)

            agent.reset("same-user", {"profile_id": "user-a"})
            agent.respond(
                "same-user",
                "I'm looking for shoes. A key requirement is: color: blue.",
                1,
                1,
            )
            trace = agent.get_trace("same-user")[-1]
            self.assertIn("color:black", trace["distilled_context"]["long_term_preferences"])
            self.assertIn("color", trace["distilled_context"]["profile_conflict_attributes"])
            self.assertEqual(trace["context_program"]["profile_weight"], 0.0)

            agent.reset("anonymous", {})
            agent.respond("anonymous", "Show me ideas.", 1, 1)
            anonymous = agent.get_trace("anonymous")[-1]
            self.assertFalse(anonymous["distilled_context"]["long_term_preferences"])
            agent.close()

    def test_two_llm_failures_open_session_circuit_breaker(self) -> None:
        class FailingRanker:
            def __init__(self) -> None:
                self.calls = 0

            def rank(self, request: SemanticRankRequest) -> SemanticRankResult:
                self.calls += 1
                return SemanticRankResult(
                    tuple(item.parent_asin for item in request.candidates),
                    False,
                    "simulated_failure",
                )

            def status(self) -> dict:
                return {"enabled": True, "backend": "test", "last_latency_ms": 5.0}

            def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.jsonl"
            rows = [
                {"parent_asin": "A", "title": "waterproof shoe", "categories": ["Shoes"]},
                {"parent_asin": "B", "title": "blue shoe", "categories": ["Shoes"]},
            ]
            catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            ranker = FailingRanker()
            agent = Agent(catalog, diagnostics=True, semantic_ranker=ranker)
            agent.reset("s", {})
            for turn in range(1, 4):
                agent.respond("s", "I'm looking for shoes.", turn, 2)

            self.assertEqual(ranker.calls, 2)
            third = agent.get_trace("s")[-1]
            self.assertFalse(third["context_program"]["semantic_ranker_enabled"])
            self.assertIn("session_llm_circuit_open", third["context_program"]["reasons"])
            agent.close()

    def test_qwen_observability_counts_fallbacks_errors_tokens_and_latency(self) -> None:
        responses = [
            {
                "message": {"content": json.dumps({"ordered_parent_asins": ["A"]})},
                "prompt_eval_count": 20,
                "eval_count": 5,
            },
            {
                "message": {"content": json.dumps({"ordered_parent_asins": ["UNKNOWN"]})},
            },
        ]

        def transport(url: str, payload: bytes, timeout_seconds: float) -> bytes:
            return json.dumps(responses.pop(0)).encode("utf-8")

        ranker = OllamaQwenSemanticRanker(
            "qwen3.5:9b",
            "http://127.0.0.1:11434",
            1000.0,
            "1m",
            0.0,
            4096,
            256,
            transport=transport,
        )
        request = SemanticRankRequest(
            query="shoe",
            routing=route_intent(SessionState("s", {}, buying_probability=0.9), SolutionConfig()),
            constraints=(),
            profile_summary="",
            candidates=(),
        )
        request = replace(
            request,
            candidates=(
                SemanticCandidate("A", "shoe", "Shoes", "", 1.0),
            ),
        )
        self.assertTrue(ranker.rank(request).applied)
        self.assertFalse(ranker.rank(request).applied)
        status = ranker.status()
        self.assertEqual(status["request_count"], 2)
        self.assertEqual(status["success_count"], 1)
        self.assertEqual(status["fallback_count"], 1)
        self.assertEqual(status["error_counts"], {"invalid_candidate_permutation": 1})
        self.assertEqual(status["total_prompt_tokens"], 20)
        self.assertEqual(status["total_completion_tokens"], 5)
        self.assertIsNotNone(status["p50_latency_ms"])
        self.assertIsNotNone(status["p95_latency_ms"])


if __name__ == "__main__":
    unittest.main()
