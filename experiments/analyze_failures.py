from __future__ import annotations

import argparse
import json
from collections import Counter

from experiments.common import read_json, resolve_path


def analyze(results: dict) -> dict:
    sessions = results.get("sessions", [])
    failures = [session for session in sessions if not session.get("hit")]
    hits = [session for session in sessions if session.get("hit")]
    ranks = Counter(str(session.get("best_rank")) for session in hits)
    return {
        "sample_count": len(sessions),
        "hit_count": len(hits),
        "failure_count": len(failures),
        "failure_rate": round(len(failures) / len(sessions), 6) if sessions else 0.0,
        "failures_by_scenario": dict(sorted(Counter(x["scenario_type"] for x in failures).items())),
        "hits_by_scenario": dict(sorted(Counter(x["scenario_type"] for x in hits).items())),
        "hit_rank_distribution": dict(sorted(ranks.items(), key=lambda item: int(item[0]))),
        "failure_sample_ids": [x["sample_id"] for x in failures],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize misses from an official evaluator result")
    parser.add_argument("results")
    parser.add_argument("--output")
    args = parser.parse_args()
    path = resolve_path(args.results)
    if path.is_dir():
        path = path / "results.json"
    report = analyze(read_json(path))
    rendered = json.dumps(report, indent=2)
    if args.output:
        resolve_path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

