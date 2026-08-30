from __future__ import annotations

import argparse
import json
from typing import Any

from experiments.common import read_json, resolve_path


METRICS = ("hit_rate_at_10", "mrr", "mttc", "efficiency", "recommended_technical_score")


def result_path(value: str):
    path = resolve_path(value)
    return path / "results.json" if path.is_dir() else path


def delta(metric: str, candidate: float, baseline: float) -> float:
    value = candidate - baseline
    return -value if metric == "mttc" else value


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    overall = {
        metric: {
            "baseline": baseline.get(metric),
            "candidate": candidate.get(metric),
            "improvement": round(delta(metric, float(candidate[metric]), float(baseline[metric])), 6),
        }
        for metric in METRICS
        if metric in baseline and metric in candidate
    }
    scenarios: dict[str, Any] = {}
    names = sorted(set(baseline.get("scenario_metrics", {})) | set(candidate.get("scenario_metrics", {})))
    for name in names:
        left = baseline.get("scenario_metrics", {}).get(name, {})
        right = candidate.get("scenario_metrics", {}).get(name, {})
        scenarios[name] = {
            metric: {
                "baseline": left.get(metric),
                "candidate": right.get(metric),
                "improvement": round(delta(metric, float(right[metric]), float(left[metric])), 6),
            }
            for metric in ("hit_rate_at_10", "mrr", "mttc")
            if metric in left and metric in right and left[metric] is not None and right[metric] is not None
        }
    return {"overall": overall, "scenarios": scenarios}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two official-evaluator result files")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    parser.add_argument("--output")
    args = parser.parse_args()
    comparison = compare(read_json(result_path(args.baseline)), read_json(result_path(args.candidate)))
    rendered = json.dumps(comparison, indent=2)
    if args.output:
        resolve_path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

