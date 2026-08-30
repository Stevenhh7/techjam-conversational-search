from __future__ import annotations

import unittest

from experiments.analyze_failures import analyze
from experiments.compare_runs import compare
from experiments.split_public_set import stratified_split


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


if __name__ == "__main__":
    unittest.main()

