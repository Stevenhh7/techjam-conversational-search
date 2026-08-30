from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from solution.agent import Agent
from solution.catalog import to_document
from solution.clarification import choose_attribute
from solution.config import SolutionConfig
from solution.generality import assess_over_generality
from solution.intent import parse_turn
from solution.llm.base import SemanticRankRequest, SemanticRankResult
from solution.llm.factory import create_semantic_ranker
from solution.llm.qwen import OllamaQwenSemanticRanker
from solution.pipeline import ProbeResult
from solution.query_builder import BuiltQuery
from solution.ranking.constraints import apply_precision_constraints
from solution.ranking.diversity import diversify_categories
from solution.ranking.semantic import semantic_rerank
from solution.retrieval.base import Candidate
from solution.retrieval.category import CategoryRetriever
from solution.retrieval.fusion import attach_route_evidence, reciprocal_rank_fusion, supplement_with_dense
from solution.retrieval.hashing import hashing_vector
from solution.retrieval.dense import DenseRetriever
from solution.routing import route_intent
from solution.schemas import ClarificationDecision, Constraint, RoutingDecision, SemanticCandidate, SessionState
from solution.state import update_state


class SolutionTests(unittest.TestCase):
    def test_override_replaces_old_constraints(self) -> None:
        state = SessionState("s", {})
        update_state(state, "I'm looking for running shoes. A key requirement is: under $100.", 1)
        update_state(state, "Actually, ignore my earlier preference. What I need is: waterproof.", 2)
        self.assertEqual(state.intent, "buying")
        self.assertEqual(state.hard_constraints, ["waterproof"])
        self.assertEqual(state.soft_preferences, [])
        self.assertIsNone(state.budget_max)
        self.assertEqual([item.value for item in state.structured_constraints], ["waterproof"])
        self.assertEqual(state.slot_store["feature"][0].value, "waterproof")
        self.assertTrue(any(item.action == "reset" for item in state.slot_history))
        self.assertTrue(any(item.to_phase == "rewriting" for item in state.transition_history))

    def test_attribute_level_override_rewrites_only_that_slot(self) -> None:
        state = SessionState("s", {})
        update_state(state, "I'm looking for jackets. A key requirement is: color: black; waterproof.", 1)
        update_state(state, "Actually, blue instead of black.", 2)
        self.assertEqual([item.value for item in state.slot_store["color"]], ["blue"])
        self.assertEqual([item.value for item in state.slot_store["feature"]], ["waterproof"])
        replacements = [item for item in state.slot_history if item.action == "replace"]
        self.assertEqual(replacements[-1].attribute, "color")
        self.assertEqual(replacements[-1].old_values, ("black",))
        self.assertEqual(replacements[-1].new_values, ("blue",))

    def test_category_override_rewrites_category_without_erasing_budget(self) -> None:
        state = SessionState("s", {})
        update_state(state, "I'm looking for running shoes. A key requirement is: under $100.", 1)
        update_state(state, "I'm looking for hiking boots instead of running shoes.", 2)
        self.assertEqual(state.category, "hiking boots")
        self.assertEqual(state.budget_max, 100.0)
        mutations = [item for item in state.slot_history if item.reason == "category_override"]
        self.assertEqual(mutations[-1].old_values, ("running shoes",))
        self.assertEqual(mutations[-1].new_values, ("hiking boots",))

    def test_state_rejects_stale_or_conflicting_turns(self) -> None:
        state = SessionState("s", {})
        message = "I'm looking for shoes, but I'm still exploring."
        update_state(state, message, 1)
        revision = state.state_revision
        self.assertIs(update_state(state, message, 1), state)
        self.assertEqual(state.state_revision, revision)
        with self.assertRaises(RuntimeError):
            update_state(state, "different", 1)
        with self.assertRaises(RuntimeError):
            update_state(state, "old", 0)

    def test_pending_clarification_types_otherwise_unknown_slot_value(self) -> None:
        state = SessionState("s", {})
        state.pending_clarification = ClarificationDecision(
            "brand", 1.0, "test", 0.0, 0.0, 0.0, (), "Which brand?"
        )
        update_state(state, "For that, what matters is: Acme.", 1)
        self.assertEqual([item.value for item in state.slot_store["brand"]], ["acme"])

        state.pending_clarification = ClarificationDecision(
            "category", 1.0, "test", 0.0, 0.0, 0.0, (), "Which category?"
        )
        update_state(state, "For that, what matters is: hiking boots.", 2)
        self.assertEqual(state.category, "hiking boots")

    def test_explicit_override_is_not_typed_by_previous_question(self) -> None:
        state = SessionState("s", {})
        update_state(state, "I'm looking for jackets. A key requirement is: cotton.", 1)
        state.pending_clarification = ClarificationDecision(
            "brand", 1.0, "test", 0.0, 0.0, 0.0, (), "Which brand?"
        )
        update_state(
            state,
            "Actually, ignore my earlier preference. What I need is: waterproof.",
            2,
        )
        self.assertEqual([item.attribute for item in state.structured_constraints], ["feature"])

    def test_router_returns_probabilities(self) -> None:
        self.assertLess(parse_turn("I'm still exploring.").buying_probability, 0.5)
        self.assertGreater(parse_turn("I need black leather boots under $100.").buying_probability, 0.5)

    def test_dual_track_router_returns_distinct_execution_plans(self) -> None:
        config = SolutionConfig()
        buying = SessionState("buy", {}, buying_probability=0.9, hard_constraints=["leather"])
        browsing = SessionState("browse", {}, buying_probability=0.2)
        buying_route = route_intent(buying, config)
        browsing_route = route_intent(browsing, config)
        self.assertEqual(buying_route.track, "precision")
        self.assertTrue(buying_route.hard_filtering)
        self.assertEqual(browsing_route.track, "discovery")
        self.assertFalse(browsing_route.hard_filtering)
        self.assertGreater(browsing_route.dense_limit, buying_route.dense_limit)
        self.assertTrue(browsing_route.diversity_enabled)

    def test_candidate_pool_overload_is_explicitly_detected(self) -> None:
        config = SolutionConfig()
        state = SessionState("s", {}, buying_probability=0.2, category="clothing")
        routing = route_intent(state, config)
        probe = ProbeResult(
            routes={"bm25": [], "category": [], "metadata": []},
            sparse_fused=[],
            unique_candidate_count=200,
            saturated_routes=("bm25", "metadata"),
        )
        result = assess_over_generality(
            state,
            BuiltQuery("clothing", "clothing", "clothing", ""),
            routing,
            probe,
            config,
        )
        self.assertTrue(result.overloaded)
        self.assertIn("candidate_pool_overload", result.reasons)
        self.assertIn("multiple_sparse_routes_saturated", result.reasons)

    def test_category_retriever_is_independent_and_deterministic(self) -> None:
        retriever = CategoryRetriever([
            to_document({"parent_asin": "A", "title": "shoe", "categories": ["Clothing", "Trail Shoes"]}),
            to_document({"parent_asin": "B", "title": "coat", "categories": ["Clothing", "Winter Coats"]}),
        ])
        first = retriever.search("trail shoes", 10)
        second = retriever.search("trail shoes", 10)
        self.assertEqual([item.parent_asin for item in first], ["A"])
        self.assertEqual([item.parent_asin for item in first], [item.parent_asin for item in second])

    def test_precision_constraints_relax_when_candidate_pool_would_collapse(self) -> None:
        products = {
            "A": {"title": "black leather boot", "features": [], "categories": ["Boots"]},
            "B": {"title": "blue fabric shoe", "features": [], "categories": ["Shoes"]},
        }
        state = SessionState("s", {}, structured_constraints=[
            Constraint("material", "contains", "leather", 0.96, 1, True, "leather")
        ])
        candidates = [Candidate("A", 1.0), Candidate("B", 0.5)]
        kept, applied, relaxed = apply_precision_constraints(candidates, products, state, 2)
        self.assertEqual([item.parent_asin for item in kept], ["A", "B"])
        self.assertEqual(applied, ())
        self.assertEqual(relaxed, ("material:leather",))

    def test_open_browsing_diversifies_equal_relevance_candidates(self) -> None:
        products = {
            "A": {"categories": ["Shoes"]},
            "B": {"categories": ["Shoes"]},
            "C": {"categories": ["Coats"]},
        }
        ranked = [Candidate("A", 1.0), Candidate("B", 0.99), Candidate("C", 0.98)]
        result = diversify_categories(ranked, products, 0.08)
        self.assertEqual([item.parent_asin for item in result[:2]], ["A", "C"])

    def test_semantic_ranker_accepts_only_complete_candidate_permutations(self) -> None:
        class ReversingRanker:
            def rank(self, request: SemanticRankRequest) -> SemanticRankResult:
                return SemanticRankResult(
                    tuple(reversed([item.parent_asin for item in request.candidates])),
                    True,
                    "fake",
                    5,
                    2,
                )

            def status(self) -> dict:
                return {"enabled": True}

            def close(self) -> None:
                return None

        candidates = [Candidate("A", 1.0), Candidate("B", 0.5)]
        products = {
            "A": {"title": "shoe", "categories": ["Shoes"]},
            "B": {"title": "coat", "categories": ["Coats"]},
        }
        routing = RoutingDecision("buying", 0.9, "precision", True, "strong", 10, 10, 10, 10, "supplement", False)
        ranked, result = semantic_rerank(
            candidates, products, "winter", SessionState("s", {}), routing, ReversingRanker(), 2
        )
        self.assertEqual([item.parent_asin for item in ranked], ["B", "A"])
        self.assertTrue(result.applied)
        self.assertEqual(result.prompt_tokens, 5)

    def test_semantic_ranker_rejects_unknown_candidate_and_falls_back(self) -> None:
        class InvalidRanker:
            def rank(self, request: SemanticRankRequest) -> SemanticRankResult:
                return SemanticRankResult(("UNKNOWN",), True, "invalid")

            def status(self) -> dict:
                return {"enabled": True}

            def close(self) -> None:
                return None

        candidates = [Candidate("A", 1.0), Candidate("B", 0.5)]
        products = {
            "A": {"title": "shoe", "categories": ["Shoes"]},
            "B": {"title": "coat", "categories": ["Coats"]},
        }
        routing = RoutingDecision("browsing", 0.8, "discovery", False, "soft", 10, 10, 10, 10, "semantic_pool", True)
        ranked, result = semantic_rerank(
            candidates, products, "ideas", SessionState("s", {}), routing, InvalidRanker(), 2
        )
        self.assertEqual([item.parent_asin for item in ranked], ["A", "B"])
        self.assertFalse(result.applied)
        self.assertIn("invalid candidate permutation", result.reason)

    def test_qwen_factory_builds_local_ollama_adapter_without_connecting(self) -> None:
        ranker = create_semantic_ranker(SolutionConfig(
            semantic_ranker_enabled=True,
            semantic_ranker_backend="ollama",
        ))
        status = ranker.status()
        self.assertTrue(status["enabled"])
        self.assertEqual(status["backend"], "ollama")
        self.assertEqual(status["model"], "qwen3.5:9b")
        self.assertEqual(status["endpoint"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(status["request_count"], 0)

    def test_ollama_qwen_uses_structured_output_and_reports_usage(self) -> None:
        captured: dict[str, object] = {}

        def transport(url: str, payload: bytes, timeout_seconds: float) -> bytes:
            captured["url"] = url
            captured["payload"] = json.loads(payload.decode("utf-8"))
            captured["timeout_seconds"] = timeout_seconds
            return json.dumps({
                "model": "qwen3.5:9b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"ordered_parent_asins": ["B", "A"]}),
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 41,
                "eval_count": 9,
                "total_duration": 123,
                "load_duration": 45,
            }).encode("utf-8")

        ranker = OllamaQwenSemanticRanker(
            "qwen3.5:9b",
            "http://127.0.0.1:11434/",
            120000.0,
            "10m",
            0.0,
            8192,
            1024,
            transport=transport,
        )
        request = SemanticRankRequest(
            query="waterproof trail shoes",
            routing=RoutingDecision(
                "buying", 0.9, "precision", True, "strong", 10, 10, 10, 10, "supplement", False
            ),
            constraints=(Constraint("feature", "contains", "waterproof", 0.95, 1, True),),
            profile_summary="outdoor runner",
            candidates=(
                SemanticCandidate("A", "Trail shoe", "Shoes", "waterproof", 0.8, (("bm25", 1),)),
                SemanticCandidate("B", "Hiking shoe", "Shoes", "waterproof", 0.7, (("dense", 1),)),
            ),
        )

        result = ranker.rank(request)
        self.assertTrue(result.applied)
        self.assertEqual(result.ordered_parent_asins, ("B", "A"))
        self.assertEqual(result.prompt_tokens, 41)
        self.assertEqual(result.completion_tokens, 9)
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(captured["timeout_seconds"], 120.0)
        payload = captured["payload"]
        self.assertEqual(payload["model"], "qwen3.5:9b")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["format"]["properties"]["ordered_parent_asins"]["minItems"], 2)
        self.assertEqual(payload["options"]["temperature"], 0.0)
        self.assertEqual(ranker.status()["success_count"], 1)

    def test_ollama_qwen_invalid_output_falls_back_without_reordering(self) -> None:
        def transport(url: str, payload: bytes, timeout_seconds: float) -> bytes:
            return json.dumps({
                "message": {
                    "content": json.dumps({"ordered_parent_asins": ["A", "A"]}),
                }
            }).encode("utf-8")

        ranker = OllamaQwenSemanticRanker(
            "qwen3.5:9b", "http://127.0.0.1:11434", 1000.0, "1m", 0.0, 4096, 256,
            transport=transport,
        )
        request = SemanticRankRequest(
            query="shoes",
            routing=RoutingDecision(
                "browsing", 0.8, "discovery", False, "soft", 10, 10, 10, 10, "semantic_pool", True
            ),
            constraints=(),
            profile_summary="",
            candidates=(
                SemanticCandidate("A", "Shoe A", "Shoes", "", 0.8),
                SemanticCandidate("B", "Shoe B", "Shoes", "", 0.7),
            ),
        )

        result = ranker.rank(request)
        self.assertFalse(result.applied)
        self.assertEqual(result.ordered_parent_asins, ("A", "B"))
        self.assertIn("invalid_candidate_permutation", result.reason)
        self.assertEqual(ranker.status()["last_error"], "invalid_candidate_permutation")

    def test_ollama_qwen_connection_failure_is_non_fatal(self) -> None:
        def unavailable(url: str, payload: bytes, timeout_seconds: float) -> bytes:
            raise TimeoutError("local Ollama is not running")

        ranker = OllamaQwenSemanticRanker(
            "qwen3.5:9b", "http://127.0.0.1:11434", 1000.0, "1m", 0.0, 4096, 256,
            transport=unavailable,
        )
        request = SemanticRankRequest(
            query="shoes",
            routing=RoutingDecision(
                "buying", 0.9, "precision", True, "strong", 10, 10, 10, 10, "supplement", False
            ),
            constraints=(),
            profile_summary="",
            candidates=(SemanticCandidate("A", "Shoe A", "Shoes", "", 0.8),),
        )

        result = ranker.rank(request)
        self.assertFalse(result.applied)
        self.assertEqual(result.ordered_parent_asins, ("A",))
        self.assertEqual(result.reason, "ollama_qwen_unavailable:TimeoutError")
        self.assertEqual(ranker.status()["last_error"], "TimeoutError")

    def test_rrf_is_deterministic(self) -> None:
        routes = {
            "bm25": [Candidate("a", 1), Candidate("b", 0.5)],
            "dense": [Candidate("b", 1), Candidate("a", 0.5)],
        }
        first = reciprocal_rank_fusion(routes, {"bm25": 1.2, "dense": 0.7})
        second = reciprocal_rank_fusion(routes, {"bm25": 1.2, "dense": 0.7})
        self.assertEqual([item.parent_asin for item in first], [item.parent_asin for item in second])
        self.assertEqual(first[0].parent_asin, "a")

    def test_rrf_does_not_admit_candidates_from_zero_weight_routes(self) -> None:
        result = reciprocal_rank_fusion(
            {"bm25": [Candidate("A", 1.0)], "category": [Candidate("B", 1.0)]},
            {"bm25": 1.0, "category": 0.0},
        )
        self.assertEqual([item.parent_asin for item in result], ["A"])

    def test_dense_supplement_does_not_boost_existing_sparse_candidate(self) -> None:
        sparse = [Candidate("a", 0.5), Candidate("b", 0.25)]
        dense = [Candidate("b", 0.99), Candidate("c", 0.90)]
        result = supplement_with_dense(sparse, dense, weight=0.45, limit=2)
        by_id = {item.parent_asin: item for item in result}
        self.assertEqual(by_id["b"].score, 0.25)
        self.assertEqual(by_id["b"].route_ranks["dense"], 1)
        self.assertLessEqual(by_id["c"].score, by_id["b"].score)

    def test_audit_route_evidence_does_not_change_precision_scores_or_membership(self) -> None:
        sparse = [Candidate("A", 0.5), Candidate("B", 0.25)]
        category = [Candidate("C", 1.0), Candidate("B", 0.8)]
        result = attach_route_evidence(sparse, category, "category")
        self.assertEqual([item.parent_asin for item in result], ["A", "B"])
        self.assertEqual(result[1].score, 0.25)
        self.assertEqual(result[1].route_ranks["category"], 2)

    def test_precision_constraint_checks_full_searchable_product_text(self) -> None:
        products = {
            "A": {"title": "bra", "description": ["soft cotton lining"], "categories": ["Bras"]},
            "B": {"title": "bra", "description": ["synthetic lining"], "categories": ["Bras"]},
        }
        state = SessionState("s", {}, structured_constraints=[
            Constraint("material", "contains", "cotton", 0.96, 1, True, "cotton")
        ])
        kept, applied, relaxed = apply_precision_constraints(
            [Candidate("A", 1.0), Candidate("B", 0.5)], products, state, 1
        )
        self.assertEqual([item.parent_asin for item in kept], ["A"])
        self.assertEqual(applied, ("material:cotton",))
        self.assertEqual(relaxed, ())

    def test_partial_dense_artifact_is_never_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            embeddings = root / "partial.npy"
            metadata = root / "partial.meta.json"
            embeddings.write_bytes(b"not-read-because-metadata-is-partial")
            metadata.write_text(json.dumps({"complete_catalog": False}), encoding="utf-8")
            retriever = DenseRetriever(embeddings, metadata, "unused", expected_count=2)
            self.assertFalse(retriever.enabled)
            self.assertIn("partial", retriever.reason)

    def test_corrupt_dense_metadata_degrades_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            embeddings = root / "broken.npy"
            metadata = root / "broken.meta.json"
            embeddings.write_bytes(b"broken")
            metadata.write_text("{not-json", encoding="utf-8")
            retriever = DenseRetriever(embeddings, metadata, "unused", expected_count=2)
            self.assertFalse(retriever.enabled)
            self.assertIn("unreadable", retriever.reason)

    def test_dense_retriever_promotes_float16_index_for_fast_exact_search(self) -> None:
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            embeddings = root / "complete.npy"
            metadata = root / "complete.meta.json"
            np.save(embeddings, np.eye(2, dtype=np.float16))
            metadata.write_text(
                json.dumps(
                    {
                        "backend": "hashing",
                        "complete_catalog": True,
                        "dimension": 2,
                        "parent_asins": ["A", "B"],
                        "catalog_row_count": 2,
                    }
                ),
                encoding="utf-8",
            )

            retriever = DenseRetriever(embeddings, metadata, "unused", expected_count=2)

            self.assertTrue(retriever.enabled)
            self.assertEqual(retriever.matrix.dtype, np.float16)
            self.assertEqual(retriever.search_matrix.dtype, np.float32)
            self.assertEqual(retriever.search_matrix.shape, retriever.matrix.shape)
            # Release the Windows memmap handle before TemporaryDirectory
            # removes the backing file.
            del retriever

    def test_hashing_dense_vector_is_normalized_and_deterministic(self) -> None:
        first = hashing_vector("waterproof trail running shoes", 64)
        second = hashing_vector("waterproof trail running shoes", 64)
        self.assertTrue((first == second).all())
        self.assertAlmostEqual(float((first @ first)), 1.0, places=5)

    def test_clarification_never_repeats(self) -> None:
        state = SessionState("s", {}, turn=1, category="shoes", asked_attributes={"feature"})
        products = {"a": {"title": "black leather waterproof running shoes", "categories": ["Shoes"]}}
        self.assertNotEqual(choose_attribute(state, ["a"], products), "feature")

    def test_agent_contract_without_dense_artifact(self) -> None:
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                catalog = Path(directory) / "catalog.jsonl"
                rows = [
                    {"parent_asin": "A", "title": "waterproof trail running shoes", "features": ["lightweight"], "categories": ["Shoes"], "rating_number": 10},
                    {"parent_asin": "B", "title": "formal leather boots", "features": ["black"], "categories": ["Boots"], "rating_number": 5},
                ]
                catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                agent = Agent(catalog)
                agent.reset("s", {"preference": "outdoor"})
                result = agent.respond("s", "I'm looking for shoes. A key requirement is: waterproof.", 1, 10)
                self.assertEqual(result["recommendations"][0]["parent_asin"], "A")
                self.assertIn(result["ask_attribute"], {"material", "color", "size", "style", "brand", "budget", "feature", "use_case"})
                self.assertEqual(result["usage"], {"prompt_tokens": 0, "completion_tokens": 0})
            finally:
                os.chdir(previous)

    def test_over_general_cutoff_skips_dense_and_ranker_then_recovers(self) -> None:
        class CountingDense:
            enabled = True
            reason = "test"
            backend = "test"

            def __init__(self) -> None:
                self.calls = 0

            def search(self, query: str, limit: int) -> list[Candidate]:
                self.calls += 1
                return []

        class CountingRanker:
            def __init__(self) -> None:
                self.calls = 0

            def rank(self, request: SemanticRankRequest) -> SemanticRankResult:
                self.calls += 1
                return SemanticRankResult(
                    tuple(item.parent_asin for item in request.candidates),
                    False,
                    "test_passthrough",
                )

            def status(self) -> dict:
                return {"enabled": True, "backend": "test"}

            def close(self) -> None:
                return None

        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                catalog = Path(directory) / "catalog.jsonl"
                rows = [
                    {"parent_asin": "A", "title": "waterproof hiking jacket", "features": ["durable"], "categories": ["Jackets"], "rating_number": 30},
                    {"parent_asin": "B", "title": "casual cotton shirt", "features": ["comfortable"], "categories": ["Shirts"], "rating_number": 20},
                    {"parent_asin": "C", "title": "winter trail boots", "features": ["waterproof"], "categories": ["Boots"], "rating_number": 10},
                ]
                catalog.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                ranker = CountingRanker()
                dense = CountingDense()
                agent = Agent(catalog, diagnostics=True, semantic_ranker=ranker)
                agent.pipeline.dense = dense
                agent.reset("s", {})

                first = agent.respond("s", "Show me ideas.", 1, 10)
                self.assertEqual(dense.calls, 0)
                self.assertEqual(ranker.calls, 0)
                self.assertIsNotNone(first["ask_attribute"])
                self.assertIn("broad set", first["message"])
                self.assertTrue(first["recommendations"])
                first_trace = agent.get_trace("s")[-1]
                self.assertTrue(first_trace["retrieval_cutoff"])
                self.assertEqual(first_trace["routes"]["dense"], [])
                self.assertEqual(first_trace["semantic_ranker"]["reason"], "over_generality_cutoff")

                repeated = agent.respond("s", "Show me ideas.", 1, 10)
                self.assertEqual(repeated, first)
                self.assertEqual(dense.calls, 0)
                self.assertEqual(ranker.calls, 0)
                self.assertEqual(len(agent.get_trace("s")), 1)

                second = agent.respond("s", "For that, what matters is: waterproof.", 2, 10)
                self.assertEqual(dense.calls, 1)
                self.assertEqual(ranker.calls, 1)
                self.assertTrue(second["recommendations"])
                second_trace = agent.get_trace("s")[-1]
                self.assertFalse(second_trace["retrieval_cutoff"])
                self.assertFalse(second_trace["over_generality"]["overloaded"])
                phases = [item.to_phase for item in agent.sessions["s"].transition_history]
                self.assertIn("overloaded", phases)
                self.assertIn("ready", phases)
                agent.close()
            finally:
                os.chdir(previous)
