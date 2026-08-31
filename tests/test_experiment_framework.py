from __future__ import annotations

import unittest

from experiments.analyze_failures import analyze
from experiments.compare_runs import compare
from experiments.split_public_set import stratified_split
from experiments.trace_failures import _aggregate_audit, _compliance_audit, _failure_reason


class ExperimentFrameworkTests(unittest.TestCase):
    def test_split_is_deterministic_and_stratified(self) -> None:
        samples = [
            {"sample_id": f"{scenario}_{index}", "scenario_type": scenario}
            for scenario in ("buying", "browsing", "intent_override", "boundary")
            for index in range(8)
        ]
        first = stratified_split(samples, 0.25, "seed")
        second = stratified_split(samples, 0.25, "seed")
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), 24)
        self.assertEqual(len(first[1]), 8)
        for scenario in ("buying", "browsing", "intent_override", "boundary"):
            self.assertEqual(sum(x["scenario_type"] == scenario for x in first[1]), 2)

    def test_compare_treats_lower_mttc_as_improvement(self) -> None:
        baseline = {
            "hit_rate_at_10": 0.1,
            "mrr": 0.05,
            "mttc": 10.0,
            "efficiency": 0.1,
            "recommended_technical_score": 0.085,
            "scenario_metrics": {},
        }
        candidate = {**baseline, "mttc": 8.5}
        self.assertEqual(compare(baseline, candidate)["overall"]["mttc"]["improvement"], 1.5)

    def test_failure_analysis(self) -> None:
        report = analyze({
            "sessions": [
                {"sample_id": "a", "scenario_type": "buying", "hit": True, "best_rank": 2},
                {"sample_id": "b", "scenario_type": "browsing", "hit": False, "best_rank": None},
            ]
        })
        self.assertEqual(report["hit_count"], 1)
        self.assertEqual(report["failure_count"], 1)
        self.assertEqual(report["hit_rank_distribution"], {"2": 1})

    def test_trace_failure_reason_includes_category_as_a_recall_route(self) -> None:
        turn = {
            "override_applied": True,
            "ranks": {
                "bm25": None,
                "category": 3,
                "metadata": None,
                "dense": None,
                "sparse_fused": None,
                "fused": None,
                "final": None,
            },
        }
        self.assertEqual(_failure_reason([turn]), "fusion_drop")

    def test_trace_failure_reason_ignores_pre_override_ranks(self) -> None:
        before_override = {
            "override_applied": False,
            "ranks": {
                "bm25": 1,
                "category": 1,
                "metadata": 1,
                "dense": 1,
                "sparse_fused": 1,
                "fused": 1,
                "final": 1,
            },
        }
        after_override = {
            "override_applied": True,
            "ranks": {
                "bm25": None,
                "category": None,
                "metadata": None,
                "dense": None,
                "sparse_fused": None,
                "fused": None,
                "final": None,
            },
        }
        self.assertEqual(
            _failure_reason([before_override, after_override]),
            "not_recalled",
        )

    def test_trace_aggregate_audit_counts_rank_buckets_and_questions(self) -> None:
        sessions = [
            {
                "best_ranks": {stage: (12 if stage == "final" else None) for stage in (
                    "bm25", "category", "metadata", "dense", "sparse_fused", "fused", "final"
                )},
                "first_recall_turn": {stage: (2 if stage == "final" else None) for stage in (
                    "bm25", "category", "metadata", "dense", "sparse_fused", "fused", "final"
                )},
                "question_audit": {"asked_attributes": ["size", "color"], "duplicate_attributes": []},
                "turns": [{
                    "retrieval_cutoff": False,
                    "semantic_ranker": {"applied": False},
                    "applied_constraints": [],
                    "relaxed_constraints": [],
                }],
            }
        ]
        audit = _aggregate_audit(sessions)
        self.assertEqual(audit["final_rank_buckets"]["11-20"], 1)
        self.assertEqual(audit["total_questions"], 2)
        self.assertEqual(audit["semantic_ranker_applied_turns"], 0)

    def test_trace_compliance_audit_validates_grounded_unique_ids(self) -> None:
        sessions = [{
            "target": "TARGET",
            "turns": [{
                "turn": 1,
                "override_applied": True,
                "recommendations": ["A", "B"],
            }],
        }]
        audit = _compliance_audit(sessions, {"A", "B", "TARGET"}, "d", "d", "c", "c")
        self.assertEqual(audit["unknown_recommendation_ids"], 0)
        self.assertEqual(audit["duplicate_recommendation_ids"], 0)
        self.assertTrue(audit["catalog_sha_unchanged"])


if __name__ == "__main__":
    unittest.main()
