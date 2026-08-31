from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from demo.app import DEMO_SCENARIOS, DemoApp, demo_config, verified_evidence


class DemoPresenterTests(unittest.TestCase):
    def test_demo_defaults_to_local_deterministic_ranking(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = demo_config()

        self.assertFalse(config.semantic_ranker_enabled)
        self.assertEqual(config.semantic_ranker_backend, "ollama")

    def test_scenarios_do_not_expose_evaluation_targets(self) -> None:
        self.assertGreaterEqual(len(DEMO_SCENARIOS), 3)
        for scenario in DemoApp.scenarios():
            self.assertNotIn("target", scenario)
            self.assertNotIn("target_asin", scenario)
            self.assertNotIn("ground_truth", scenario)
            self.assertTrue(scenario["first_message"])

    def test_verified_evidence_is_aggregate_only(self) -> None:
        evidence = verified_evidence()

        self.assertEqual(evidence["source"], "tracked dev150 summaries")
        self.assertEqual(evidence["sample_count"], 150)
        self.assertAlmostEqual(evidence["metrics"]["hit_rate_at_10"], 0.92)
        self.assertNotIn("sessions", evidence)
        self.assertNotIn("targets", evidence)

    def test_prediction_exposes_runtime_program_without_candidate_ids(self) -> None:
        trace = {
            "intent": "browsing",
            "buying_probability": 0.1,
            "routing": {"track": "browsing"},
            "state": {"dialogue_phase": "clarifying"},
            "distilled_context": {"summary": "waterproof"},
            "context_program": {"reasons": ["browsing_diversity"]},
            "strategy_outcome": {"unique_candidate_count": 200},
            "semantic_ranker": {"applied": False, "reason": "disabled"},
            "retrieval_cutoff": True,
            "routes": {"bm25": ["A", "B"], "dense": ["B"]},
            "final": ["B", "A"],
        }

        prediction = DemoApp._prediction(trace, {"enabled": False})

        self.assertEqual(prediction["routes"], {"bm25": 2, "dense": 1})
        self.assertEqual(prediction["final_count"], 2)
        self.assertEqual(prediction["distilled_context"]["summary"], "waterproof")
        self.assertNotIn("final", prediction)


if __name__ == "__main__":
    unittest.main()
