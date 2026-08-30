from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from solution.agent import Agent
from solution.clarification import choose_attribute
from solution.intent import parse_turn
from solution.retrieval.base import Candidate
from solution.retrieval.fusion import reciprocal_rank_fusion, supplement_with_dense
from solution.retrieval.hashing import hashing_vector
from solution.retrieval.dense import DenseRetriever
from solution.schemas import SessionState
from solution.state import update_state


class SolutionTests(unittest.TestCase):
    def test_override_replaces_old_constraints(self) -> None:
        state = SessionState("s", {})
        update_state(state, "I'm looking for running shoes. A key requirement is: lightweight.", 1)
        update_state(state, "Actually, ignore my earlier preference. What I need is: waterproof.", 2)
        self.assertEqual(state.intent, "buying")
        self.assertEqual(state.hard_constraints, ["waterproof"])
        self.assertEqual(state.soft_preferences, [])

    def test_router_returns_probabilities(self) -> None:
        self.assertLess(parse_turn("I'm still exploring.").buying_probability, 0.5)
        self.assertGreater(parse_turn("I need black leather boots under $100.").buying_probability, 0.5)

    def test_rrf_is_deterministic(self) -> None:
        routes = {
            "bm25": [Candidate("a", 1), Candidate("b", 0.5)],
            "dense": [Candidate("b", 1), Candidate("a", 0.5)],
        }
        first = reciprocal_rank_fusion(routes, {"bm25": 1.2, "dense": 0.7})
        second = reciprocal_rank_fusion(routes, {"bm25": 1.2, "dense": 0.7})
        self.assertEqual([item.parent_asin for item in first], [item.parent_asin for item in second])
        self.assertEqual(first[0].parent_asin, "a")

    def test_dense_supplement_does_not_boost_existing_sparse_candidate(self) -> None:
        sparse = [Candidate("a", 0.5), Candidate("b", 0.25)]
        dense = [Candidate("b", 0.99), Candidate("c", 0.90)]
        result = supplement_with_dense(sparse, dense, weight=0.45, limit=2)
        by_id = {item.parent_asin: item for item in result}
        self.assertEqual(by_id["b"].score, 0.25)
        self.assertEqual(by_id["b"].route_ranks["dense"], 1)
        self.assertLessEqual(by_id["c"].score, by_id["b"].score)

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
