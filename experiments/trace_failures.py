from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
)
from experiments.common import load_agent, resolve_path, write_json


STAGES = ("bm25", "category", "metadata", "dense", "sparse_fused", "fused", "final")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace route and final ranks for failed evaluator sessions")
    parser.add_argument("--results", required=True, help="results.json whose misses should be traced")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--agent", default="solution.agent:Agent")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _rank(values: list[str], target: str) -> int | None:
    try:
        return values.index(target) + 1
    except ValueError:
        return None


def _failure_reason(turns: list[dict]) -> str:
    turns = [turn for turn in turns if turn["override_applied"]]
    if not any(turn["ranks"][route] is not None for turn in turns for route in ("bm25", "metadata", "dense")):
        return "not_recalled"
    if not any(turn["ranks"]["fused"] is not None for turn in turns):
        return "fusion_drop"
    if not any(turn["ranks"]["final"] is not None for turn in turns):
        return "constraint_filter_drop"
    return "final_rank_over_10"


def _markdown(report: dict) -> str:
    lines = [
        "# 失败会话逐轮路由审计",
        "",
        f"- 失败会话：{report['failure_count']}",
        f"- override miss：{report['override_failure_count']}",
        "- 原因分布：" + ", ".join(f"{key}={value}" for key, value in report["reason_counts"].items()),
        "",
        "| sample_id | scenario | 原因 | 最佳 BM25 | 最佳 Dense | 最佳 Fused | 最佳 Final |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for session in report["sessions"]:
        best = session["best_ranks"]
        display = lambda value: "-" if value is None else str(value)
        lines.append(
            f"| {session['sample_id']} | {session['scenario_type']} | {session['failure_reason']} | "
            f"{display(best['bm25'])} | {display(best['dense'])} | {display(best['fused'])} | "
            f"{display(best['final'])} |"
        )
    lines.extend([
        "",
        "> `final` 为完整重排列表的位置；官方命中只接受前 10。完整逐轮查询、约束、提问和各路由 rank 见同目录 JSON。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    results = json.loads(resolve_path(args.results).read_text(encoding="utf-8"))
    failed_ids = {str(item["sample_id"]) for item in results["sessions"] if not item["hit"]}
    samples = [item for item in load_jsonl(resolve_path(args.dataset)) if str(item["sample_id"]) in failed_ids]
    catalog_path = resolve_path(args.catalog)
    _, categories, products = catalog_index(catalog_path)
    agent_class = load_agent(args.agent)
    agent = agent_class(catalog_path, diagnostics=True)
    sessions: list[dict] = []
    try:
        for sample in samples:
            sample_id = str(sample["sample_id"])
            print(f"tracing {sample_id} ({sample['scenario_type']})", flush=True)
            session_id = f"trace_{sample_id}"
            target = str(sample["ground_truth"]["parent_asin"])
            card, behavior = materialize_hidden_fields(sample, products)
            effective = {**sample, "intent_card": card, "behavior": behavior}
            disclosed: set[str] = set()
            boundary_used = False
            override_applied = sample["scenario_type"] != "intent_override"
            user_message = initial_message(effective, coarse_category(categories.get(target, [])), disclosed)
            agent.reset(session_id, sample.get("user_profile") or {})
            turns: list[dict] = []
            for turn in range(1, MAX_TURNS + 1):
                response = agent.respond(session_id, user_message, turn, TOP_K)
                trace = agent.get_trace(session_id)[-1]
                stage_values = {
                    "bm25": trace["routes"]["bm25"],
                    "category": trace["routes"]["category"],
                    "metadata": trace["routes"]["metadata"],
                    "dense": trace["routes"]["dense"],
                    "sparse_fused": trace["sparse_fused"],
                    "fused": trace["fused"],
                    "final": trace["final"],
                }
                turns.append({
                    "turn": turn,
                    "override_applied": override_applied,
                    "user_message": user_message,
                    "ask_attribute": response.get("ask_attribute"),
                    "query": trace["query"],
                    "routing": trace.get("routing", {}),
                    "state": trace["state"],
                    "probe": trace.get("probe", {}),
                    "over_generality": trace.get("over_generality", {}),
                    "retrieval_cutoff": trace.get("retrieval_cutoff", False),
                    "clarification": trace.get("clarification", {}),
                    "applied_constraints": trace.get("applied_constraints", []),
                    "relaxed_constraints": trace.get("relaxed_constraints", []),
                    "diversity_applied": trace.get("diversity_applied", False),
                    "ranks": {stage: _rank(values, target) for stage, values in stage_values.items()},
                    "recommendations": [str(item["parent_asin"]) for item in response["recommendations"]],
                })
                if turn == MAX_TURNS:
                    break
                override = effective.get("behavior", {}).get("override") or {}
                if not override_applied and turn + 1 == int(override.get("turn", 3)):
                    override_applied = True
                    new_value = str(override.get("new_value", ""))
                    if new_value:
                        disclosed.add(new_value)
                    user_message = str(override.get("message", "Actually, please ignore my earlier preference."))
                else:
                    user_message, boundary_used = customer_reply(
                        effective, response.get("ask_attribute"), disclosed, boundary_used
                    )
            eligible_turns = [turn for turn in turns if turn["override_applied"]]
            best_ranks = {
                stage: min((value for value in (turn["ranks"][stage] for turn in turns) if value is not None), default=None)
                for stage in STAGES
            }
            eligible_best_ranks = {
                stage: min(
                    (value for value in (turn["ranks"][stage] for turn in eligible_turns) if value is not None),
                    default=None,
                )
                for stage in STAGES
            }
            sessions.append({
                "sample_id": sample_id,
                "scenario_type": sample["scenario_type"],
                "target": target,
                "failure_reason": _failure_reason(turns),
                "all_turn_best_ranks": best_ranks,
                "best_ranks": eligible_best_ranks,
                "turns": turns,
            })
    finally:
        agent.close()

    sessions.sort(key=lambda item: (item["scenario_type"] != "intent_override", item["sample_id"]))
    reason_counts = Counter(item["failure_reason"] for item in sessions)
    report = {
        "source_results": str(resolve_path(args.results)),
        "failure_count": len(sessions),
        "override_failure_count": sum(item["scenario_type"] == "intent_override" for item in sessions),
        "dense_status": {"enabled": agent.dense.enabled, "reason": agent.dense.reason, "backend": getattr(agent.dense, "backend", None)},
        "reason_counts": dict(sorted(reason_counts.items())),
        "sessions": sessions,
    }
    output = resolve_path(args.output)
    write_json(output, report)
    output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("failure_count", "override_failure_count", "reason_counts", "dense_status")}, indent=2))


if __name__ == "__main__":
    main()
