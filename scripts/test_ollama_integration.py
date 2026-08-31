from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solution.agent import Agent
from solution.config import SolutionConfig


LIVE_SCENARIOS = (
    {
        "name": "buying",
        "message": "I need waterproof black hiking boots under $150 for winter trails.",
        "expect_llm": True,
    },
    {
        "name": "browsing",
        "message": "I'm looking for backpacks, show me ideas for a lightweight casual college option with laptop storage.",
        "expect_llm": True,
    },
    {
        "name": "over_general_cutoff",
        "message": "Show me some ideas.",
        "expect_llm": False,
        "expected_reason": "over_generality_cutoff",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a catalog-grounded live smoke test against local Ollama Qwen3.5."
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--timeout-ms", type=float, default=120000.0)
    parser.add_argument("--output", help="Optional JSON report path")
    return parser.parse_args()


def installed_models(base_url: str, timeout_seconds: float = 10.0) -> set[str]:
    with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=timeout_seconds) as response:
        payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    return {
        str(item.get("name", ""))
        for item in payload.get("models", [])
        if isinstance(item, dict) and item.get("name")
    }


def main() -> None:
    args = parse_args()
    catalog_path = Path(args.catalog).resolve()
    if not catalog_path.is_file():
        raise SystemExit(f"catalog not found: {catalog_path}")

    models = installed_models(args.base_url)
    if args.model not in models:
        raise SystemExit(
            f"Ollama model {args.model!r} is not installed; available models: {sorted(models)}"
        )

    config = SolutionConfig(
        semantic_ranker_enabled=True,
        semantic_ranker_backend="ollama",
        semantic_ranker_model=args.model,
        semantic_ranker_base_url=args.base_url,
        semantic_ranker_top_n=args.top_n,
        semantic_ranker_timeout_ms=args.timeout_ms,
    )
    started = time.perf_counter()
    agent = Agent(catalog_path, config=config, diagnostics=True)
    scenario_results: list[dict[str, object]] = []
    validation_errors: list[str] = []
    try:
        catalog_ids = set(agent.products)
        for index, scenario in enumerate(LIVE_SCENARIOS, start=1):
            session_id = f"ollama-live-{scenario['name']}"
            agent.reset(session_id, {"summary": "prefers practical, durable products"})
            request_count_before = int(agent.semantic_ranker.status()["request_count"])
            response = agent.respond(session_id, str(scenario["message"]), 1, 10)
            trace = agent.get_trace(session_id)[-1]
            semantic = trace["semantic_ranker"]
            request_count_after = int(semantic["request_count"])
            request_delta = request_count_after - request_count_before
            recommendations = [item["parent_asin"] for item in response["recommendations"]]

            scenario_errors: list[str] = []
            if len(recommendations) != len(set(recommendations)):
                scenario_errors.append("duplicate recommendation ID")
            if not set(recommendations).issubset(catalog_ids):
                scenario_errors.append("recommendation escaped the catalog")
            if bool(semantic["applied"]) != bool(scenario["expect_llm"]):
                scenario_errors.append(
                    f"expected applied={scenario['expect_llm']}, "
                    f"got {semantic['applied']} ({semantic['reason']})"
                )
            expected_request_delta = 1 if scenario["expect_llm"] else 0
            if request_delta != expected_request_delta:
                scenario_errors.append(
                    f"expected {expected_request_delta} Ollama request(s), "
                    f"got {request_delta}"
                )
            expected_reason = scenario.get("expected_reason")
            if expected_reason and semantic["reason"] != expected_reason:
                scenario_errors.append(
                    f"expected reason={expected_reason}, "
                    f"got {semantic['reason']}"
                )
            validation_errors.extend(
                f"{scenario['name']}: {message}" for message in scenario_errors
            )

            scenario_results.append(
                {
                    "sequence": index,
                    "name": scenario["name"],
                    "message": scenario["message"],
                    "intent": trace["intent"],
                    "track": trace["routing"]["track"],
                    "retrieval_cutoff": trace["retrieval_cutoff"],
                    "llm_applied": semantic["applied"],
                    "llm_reason": semantic["reason"],
                    "llm_request_delta": request_delta,
                    "llm_latency_ms": semantic["last_latency_ms"] if request_delta else None,
                    "prompt_tokens": response["usage"]["prompt_tokens"],
                    "completion_tokens": response["usage"]["completion_tokens"],
                    "ask_attribute": response["ask_attribute"],
                    "recommendations": recommendations,
                    "catalog_grounded": True,
                    "passed": not scenario_errors,
                    "validation_errors": scenario_errors,
                }
            )
    finally:
        agent.close()

    report = {
        "status": "passed" if not validation_errors else "failed",
        "validation_errors": validation_errors,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "base_url": args.base_url,
        "semantic_ranker_top_n": args.top_n,
        "timeout_ms": args.timeout_ms,
        "catalog": str(catalog_path),
        "dense_status": {
            "enabled": agent.dense.enabled,
            "backend": getattr(agent.dense, "backend", None),
            "reason": agent.dense.reason,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "scenarios": scenario_results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if validation_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
