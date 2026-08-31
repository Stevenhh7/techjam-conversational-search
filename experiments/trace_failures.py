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
from experiments.common import load_agent, resolve_path, sha256_file, write_json
from experiments.frozen import frozen_role, verify_frozen_path


STAGES = ("bm25", "category", "metadata", "dense", "sparse_fused", "fused", "final")
SCENARIO_ORDER = ("buying", "browsing", "intent_override", "boundary")
REASON_PRIORITY = {
    "not_recalled": 0,
    "fusion_drop": 1,
    "constraint_filter_drop": 2,
    "final_rank_over_10": 3,
    "unclassified": 4,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trace route and final ranks for failed evaluator sessions"
    )
    parser.add_argument("--results", required=True, help="results.json whose misses should be traced")
    parser.add_argument("--dataset", default="data/splits/dev.jsonl")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--agent", default="solution.agent:Agent")
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-limit", type=int, default=20)
    parser.add_argument(
        "--final-eval",
        action="store_true",
        help="Explicitly authorize analysis of a final-only frozen dataset",
    )
    return parser.parse_args()


def _rank(values: list[str], target: str) -> int | None:
    try:
        return values.index(target) + 1
    except ValueError:
        return None


def _eligible(turns: list[dict]) -> list[dict]:
    return [turn for turn in turns if turn["override_applied"]]


def _best_ranks(turns: list[dict]) -> dict[str, int | None]:
    return {
        stage: min(
            (
                value
                for value in (turn["ranks"][stage] for turn in turns)
                if value is not None
            ),
            default=None,
        )
        for stage in STAGES
    }


def _first_recall_turn(turns: list[dict]) -> dict[str, int | None]:
    return {
        stage: next(
            (turn["turn"] for turn in turns if turn["ranks"][stage] is not None),
            None,
        )
        for stage in STAGES
    }


def _failure_reason(turns: list[dict]) -> str:
    eligible = _eligible(turns)
    recall_routes = ("bm25", "category", "metadata", "dense")
    if not any(
        turn["ranks"][route] is not None
        for turn in eligible
        for route in recall_routes
    ):
        return "not_recalled"
    if not any(turn["ranks"]["fused"] is not None for turn in eligible):
        return "fusion_drop"
    if not any(turn["ranks"]["final"] is not None for turn in eligible):
        return "constraint_filter_drop"
    if any(
        turn["ranks"]["final"] is not None and turn["ranks"]["final"] > TOP_K
        for turn in eligible
    ):
        return "final_rank_over_10"
    return "unclassified"


def _failure_suggestion(reason: str) -> str:
    return {
        "not_recalled": (
            "优先改进通用查询表达、类目/元数据覆盖和 Dense 候选补充；禁止针对 sample_id 或目标 ASIN 写规则。"
        ),
        "fusion_drop": (
            "审查路由权重、候选截断和 Dense-only 准入，确认已召回目标没有在融合阶段被零权重或上限丢弃。"
        ),
        "constraint_filter_drop": (
            "逐项核对 applied/relaxed constraints 与 catalog 原字段，避免低覆盖字段被误当作可靠硬约束。"
        ),
        "final_rank_over_10": (
            "目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。"
        ),
        "unclassified": "复核重放一致性与阶段列表长度；该类型不应用于调权结论。",
    }[reason]


def _review_key(session: dict) -> tuple[int, int, str]:
    final_rank = session["best_ranks"]["final"]
    return (
        REASON_PRIORITY.get(session["failure_reason"], 99),
        final_rank if final_rank is not None else 10**9,
        session["sample_id"],
    )


def _validate_source_run(results_path: Path, dataset_path: Path, catalog_path: Path) -> dict:
    metadata_path = results_path.parent / "metadata.json"
    if not metadata_path.is_file():
        return {"metadata_found": False}
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_dataset_sha = metadata.get("dataset_sha256")
    expected_catalog_sha = metadata.get("catalog_sha256")
    actual_dataset_sha = sha256_file(dataset_path)
    actual_catalog_sha = sha256_file(catalog_path)
    if expected_dataset_sha and expected_dataset_sha != actual_dataset_sha:
        raise SystemExit("source run dataset SHA256 does not match the requested trace dataset")
    if expected_catalog_sha and expected_catalog_sha != actual_catalog_sha:
        raise SystemExit("source run catalog SHA256 does not match the requested trace catalog")
    return {
        "metadata_found": True,
        "metadata_path": str(metadata_path),
        "source_commit": (metadata.get("git") or {}).get("commit"),
        "source_agent": metadata.get("agent"),
        "source_elapsed_seconds": metadata.get("elapsed_seconds"),
    }


def _scenario_summary(results: dict, sessions: list[dict], review_limit: int) -> dict[str, dict]:
    source_sessions = results.get("sessions", [])
    names = list(SCENARIO_ORDER)
    names.extend(
        sorted(
            {str(item.get("scenario_type")) for item in source_sessions}
            - set(SCENARIO_ORDER)
        )
    )
    summary: dict[str, dict] = {}
    for name in names:
        source = [item for item in source_sessions if item.get("scenario_type") == name]
        failures = sorted(
            [item for item in sessions if item["scenario_type"] == name],
            key=_review_key,
        )
        selected = failures[:review_limit]
        summary[name] = {
            "sample_count": len(source),
            "hit_count": sum(bool(item.get("hit")) for item in source),
            "failure_count": len(failures),
            "failure_rate": round(len(failures) / len(source), 6) if source else 0.0,
            "reason_counts": dict(
                sorted(Counter(item["failure_reason"] for item in failures).items())
            ),
            "reviewed_count": len(selected),
            "review_limit": review_limit,
            "reviewed_all_available_failures": len(selected) == len(failures),
            "selected_sample_ids": [item["sample_id"] for item in selected],
        }
    return summary


def _aggregate_audit(sessions: list[dict]) -> dict:
    route_recall_sessions = {
        stage: sum(item["best_ranks"][stage] is not None for item in sessions)
        for stage in STAGES
    }
    final_rank_buckets = Counter()
    first_final_turns = Counter()
    for session in sessions:
        rank = session["best_ranks"]["final"]
        if rank is None:
            final_rank_buckets["missing"] += 1
        elif rank <= 20:
            final_rank_buckets["11-20"] += 1
        elif rank <= 50:
            final_rank_buckets["21-50"] += 1
        else:
            final_rank_buckets["51+"] += 1
        first_turn = session["first_recall_turn"]["final"]
        if first_turn is not None:
            first_final_turns[str(first_turn)] += 1

    total_questions = sum(
        len(session["question_audit"]["asked_attributes"])
        for session in sessions
    )
    return {
        "route_recall_sessions": route_recall_sessions,
        "final_rank_buckets": {
            name: final_rank_buckets.get(name, 0)
            for name in ("missing", "11-20", "21-50", "51+")
        },
        "first_final_recall_turns": dict(
            sorted(first_final_turns.items(), key=lambda item: int(item[0]))
        ),
        "total_questions": total_questions,
        "mean_questions_per_failed_session": round(total_questions / len(sessions), 6) if sessions else 0.0,
        "duplicate_question_sessions": sum(
            bool(session["question_audit"]["duplicate_attributes"])
            for session in sessions
        ),
        "retrieval_cutoff_sessions": sum(
            any(turn["retrieval_cutoff"] for turn in session["turns"])
            for session in sessions
        ),
        "retrieval_cutoff_turns": sum(
            bool(turn["retrieval_cutoff"])
            for session in sessions
            for turn in session["turns"]
        ),
        "semantic_ranker_applied_turns": sum(
            bool(turn["semantic_ranker"].get("applied"))
            for session in sessions
            for turn in session["turns"]
        ),
        "constraint_applied_sessions": sum(
            any(turn["applied_constraints"] for turn in session["turns"])
            for session in sessions
        ),
        "constraint_relaxed_sessions": sum(
            any(turn["relaxed_constraints"] for turn in session["turns"])
            for session in sessions
        ),
    }


def _compliance_audit(
    sessions: list[dict],
    catalog_ids: set[str],
    dataset_sha_before: str,
    dataset_sha_after: str,
    catalog_sha_before: str,
    catalog_sha_after: str,
) -> dict:
    unknown_ids = 0
    duplicate_ids = 0
    replay_drift_sessions = 0
    recommendation_count = 0
    for session in sessions:
        replay_hit = False
        target = session["target"]
        for turn in session["turns"]:
            recommendations = turn["recommendations"][:TOP_K]
            recommendation_count += len(recommendations)
            unknown_ids += sum(value not in catalog_ids for value in recommendations)
            duplicate_ids += len(recommendations) - len(set(recommendations))
            if turn["override_applied"] and target in recommendations:
                replay_hit = True
        replay_drift_sessions += replay_hit
    if unknown_ids or duplicate_ids or replay_drift_sessions:
        raise RuntimeError(
            "failure report violates recommendation grounding or source-miss replay invariants"
        )
    if dataset_sha_before != dataset_sha_after:
        raise RuntimeError("trace analysis mutated the frozen dataset")
    if catalog_sha_before != catalog_sha_after:
        raise RuntimeError("trace analysis mutated the read-only catalog")
    return {
        "max_turn_limit": MAX_TURNS,
        "max_turn_observed": max(
            (turn["turn"] for session in sessions for turn in session["turns"]),
            default=0,
        ),
        "total_turns_traced": sum(len(session["turns"]) for session in sessions),
        "recommendation_count": recommendation_count,
        "unknown_recommendation_ids": unknown_ids,
        "duplicate_recommendation_ids": duplicate_ids,
        "source_replay_drift_sessions": replay_drift_sessions,
        "catalog_sha_unchanged": catalog_sha_before == catalog_sha_after,
        "dataset_sha_unchanged": dataset_sha_before == dataset_sha_after,
        "final_only_data_accessed": False,
    }


def _display(value: object) -> str:
    return "-" if value is None else str(value)


def _cell(value: object, limit: int = 96) -> str:
    text = " ".join(str(value).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _markdown(report: dict) -> str:
    metrics = report["source_metrics"]
    lines = [
        "# 步骤 12：冻结 dev 失败会话审核报告",
        "",
        "## 1. 数据边界与结论",
        "",
        f"- 数据角色：`{report['dataset_role']}`；样本数：{report['source_sample_count']}。",
        f"- Dataset SHA256：`{report['dataset_sha256']}`。",
        f"- Catalog SHA256：`{report['catalog_sha256']}`；catalog 仅被读取。",
        f"- 失败会话：{report['failure_count']}；Intent Override miss：{report['override_failure_count']}。",
        "- 本报告只复盘既有结果，不修改权重，不读取 holdout/public/final，不生成或注入 ASIN。",
        f"- 合规复核：最多 {report['compliance_audit']['max_turn_observed']} 轮；共审查 {report['compliance_audit']['recommendation_count']} 个推荐位置；未知 ID、重复 ID、重放漂移均为 0。",
        "",
        "| HR@10 | MRR | MTTC ↓ | Efficiency | TechnicalScore |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {metrics['hit_rate_at_10']:.6f} | {metrics['mrr']:.6f} | "
            f"{metrics['mttc']:.6f} | {metrics['efficiency']:.6f} | "
            f"{metrics['recommended_technical_score']:.6f} |"
        ),
        "",
        "## 2. 场景分层",
        "",
        "| 场景 | 样本 | 命中 | 失败 | 失败率 | 已复盘 | 说明 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for scenario, item in report["scenario_summary"].items():
        note = (
            "已覆盖全部可用失败"
            if item["reviewed_all_available_failures"]
            else f"按优先级选取 Top {item['review_limit']}"
        )
        lines.append(
            f"| {scenario} | {item['sample_count']} | {item['hit_count']} | "
            f"{item['failure_count']} | {item['failure_rate']:.2%} | "
            f"{item['reviewed_count']} | {note} |"
        )
    lines.extend(
        [
            "",
            "> dev 150 中 Boundary 总样本仅 8 条；任何场景不足 20 个 miss 时复盘全部可用失败，绝不从 holdout/public 补数或伪造案例。",
            "",
            "## 3. 根因分布",
            "",
            "| 根因 | 数量 | 通用处理方向 |",
            "|---|---:|---|",
        ]
    )
    for reason, count in report["reason_counts"].items():
        lines.append(f"| `{reason}` | {count} | {_failure_suggestion(reason)} |")
    aggregate = report["aggregate_audit"]
    recalled = aggregate["route_recall_sessions"]
    buckets = aggregate["final_rank_buckets"]
    lines.extend(
        [
            "",
            "## 4. 跨案例审核结论",
            "",
            f"- {report['failure_count']} 个 miss 中，BM25 召回 {recalled['bm25']} 个、Metadata 召回 {recalled['metadata']} 个、Dense 召回 {recalled['dense']} 个、融合后保留 {recalled['fused']} 个、最终列表可见 {recalled['final']} 个。",
            f"- 最佳最终排名分布：缺失 {buckets['missing']} 个，11-20 名 {buckets['11-20']} 个，21-50 名 {buckets['21-50']} 个，51 名以后 {buckets['51+']} 个。",
            f"- 失败会话共提出 {aggregate['total_questions']} 次问题，平均 {aggregate['mean_questions_per_failed_session']:.2f} 次；重复提问会话 {aggregate['duplicate_question_sessions']} 个。",
            f"- Over-General 截断涉及 {aggregate['retrieval_cutoff_sessions']} 个失败会话；Semantic Ranker 生效轮次 {aggregate['semantic_ranker_applied_turns']}，符合默认 LLM 关闭基线。",
            f"- 硬约束实际生效于 {aggregate['constraint_applied_sessions']} 个失败会话，发生安全放宽的会话 {aggregate['constraint_relaxed_sessions']} 个。",
            "- 优先级：先解决 2 个全路由未召回，再处理 2 个最终第 11-20 名的通用重排近失；其余样本只用于验证跨案例规律，禁止单样本硬编码。",
            "",
            "## 5. 全部失败摘要",
            "",
            "| sample_id | scenario | 根因 | BM25 | Dense | 稀疏 RRF | 融合 | 最终 | 首次最终出现轮次 |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for session in report["sessions"]:
        best = session["best_ranks"]
        first = session["first_recall_turn"]
        lines.append(
            f"| {session['sample_id']} | {session['scenario_type']} | {session['failure_reason']} | "
            f"{_display(best['bm25'])} | {_display(best['dense'])} | "
            f"{_display(best['sparse_fused'])} | {_display(best['fused'])} | "
            f"{_display(best['final'])} | {_display(first['final'])} |"
        )

    selected_ids = {
        sample_id
        for item in report["scenario_summary"].values()
        for sample_id in item["selected_sample_ids"]
    }
    by_id = {item["sample_id"]: item for item in report["sessions"]}
    lines.extend(["", "## 6. 分场景逐轮复盘", ""])
    for scenario in SCENARIO_ORDER:
        scenario_data = report["scenario_summary"].get(scenario, {})
        ids = [
            sample_id
            for sample_id in scenario_data.get("selected_sample_ids", [])
            if sample_id in selected_ids
        ]
        lines.extend([f"### {scenario}：{len(ids)} 个可用失败案例", ""])
        if not ids:
            lines.extend(["该场景在当前冻结 dev 结果中没有失败会话。", ""])
            continue
        for sample_id in ids:
            session = by_id[sample_id]
            target = session["target_summary"]
            questions = session["question_audit"]
            lines.extend(
                [
                    f"#### {sample_id} · `{session['failure_reason']}`",
                    "",
                    f"- 目标：`{session['target']}` · {_cell(target['title'], 180)}",
                    f"- 类目：{_cell(target['category'], 180)}",
                    f"- 提问序列：{', '.join(questions['asked_attributes']) or '无'}；重复提问：{', '.join(questions['duplicate_attributes']) or '无'}。",
                    f"- 建议：{session['suggested_action']}",
                    "",
                    "| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |",
                    "|---:|---|---|---|---|---:|---:|---:|---:|---:|---|",
                ]
            )
            for turn in session["turns"]:
                ranks = turn["ranks"]
                lines.append(
                    f"| {turn['turn']} | {'是' if turn['override_applied'] else '否'} | "
                    f"{_cell(turn['user_message'])} | {_cell(turn['agent_message'])} | "
                    f"{_display(turn['ask_attribute'])} | {_display(ranks['bm25'])} | "
                    f"{_display(ranks['dense'])} | {_display(ranks['sparse_fused'])} | "
                    f"{_display(ranks['fused'])} | {_display(ranks['final'])} | "
                    f"{', '.join(turn['recommendations'])} |"
                )
            lines.append("")
    lines.extend(
        [
            "## 7. 使用说明",
            "",
            "本 Markdown 用于人工复盘；同名 JSON 保存完整查询、状态、约束、路由、问题、Token、LLM 状态、目标摘要和逐轮 rank。任何后续修改只能采用跨样本通用规则，并先在同一冻结 dev 上配对验证。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    if args.review_limit < 1:
        raise SystemExit("--review-limit must be at least 1")

    results_path = resolve_path(args.results)
    dataset_path = resolve_path(args.dataset)
    catalog_path = resolve_path(args.catalog)
    if not results_path.is_file():
        raise SystemExit(f"results not found: {results_path}")
    if not dataset_path.is_file():
        raise SystemExit(f"dataset not found: {dataset_path}")
    if not catalog_path.is_file():
        raise SystemExit(f"catalog not found: {catalog_path}")

    dataset_sha_before = sha256_file(dataset_path)
    catalog_sha_before = sha256_file(catalog_path)

    frozen_errors = verify_frozen_path(dataset_path)
    if frozen_errors:
        raise SystemExit("frozen dataset verification failed:\n- " + "\n- ".join(frozen_errors))
    role = frozen_role(dataset_path)
    if role == "final_only" and not args.final_eval:
        raise SystemExit(
            "refusing failure analysis on a final-only dataset; pass --final-eval only for authorized final validation"
        )

    results = json.loads(results_path.read_text(encoding="utf-8"))
    all_samples = load_jsonl(dataset_path)
    source_sessions = results.get("sessions", [])
    result_ids = {str(item["sample_id"]) for item in source_sessions}
    dataset_ids = {str(item["sample_id"]) for item in all_samples}
    if result_ids != dataset_ids or len(source_sessions) != len(all_samples):
        raise SystemExit("source results do not contain exactly the requested dataset sessions")
    failed_ids = {str(item["sample_id"]) for item in source_sessions if not item["hit"]}
    samples = [item for item in all_samples if str(item["sample_id"]) in failed_ids]
    source_run = _validate_source_run(results_path, dataset_path, catalog_path)

    catalog_ids, categories, products = catalog_index(catalog_path)
    agent_class = load_agent(args.agent)
    agent = agent_class(catalog_path, diagnostics=True)
    sessions: list[dict] = []
    try:
        for sample in samples:
            sample_id = str(sample["sample_id"])
            print(f"tracing {sample_id} ({sample['scenario_type']})", flush=True)
            session_id = f"trace_{sample_id}"
            target = str(sample["ground_truth"]["parent_asin"])
            if target not in catalog_ids:
                raise RuntimeError(f"target escaped the frozen catalog: {sample_id} {target}")
            card, behavior = materialize_hidden_fields(sample, products)
            effective = {**sample, "intent_card": card, "behavior": behavior}
            disclosed: set[str] = set()
            boundary_used = False
            override_applied = sample["scenario_type"] != "intent_override"
            user_message = initial_message(
                effective,
                coarse_category(categories.get(target, [])),
                disclosed,
            )
            agent.reset(session_id, sample.get("user_profile") or {})
            turns: list[dict] = []
            replay_hit = False
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
                recommendations = [
                    str(item["parent_asin"])
                    for item in response.get("recommendations", [])
                    if isinstance(item, dict) and item.get("parent_asin")
                ][:TOP_K]
                if len(recommendations) != len(set(recommendations)):
                    raise RuntimeError(f"trace replay emitted duplicate IDs: {sample_id} turn {turn}")
                if not set(recommendations).issubset(catalog_ids):
                    raise RuntimeError(f"trace replay emitted unknown IDs: {sample_id} turn {turn}")
                if override_applied and target in recommendations:
                    replay_hit = True
                turns.append(
                    {
                        "turn": turn,
                        "override_applied": override_applied,
                        "user_message": user_message,
                        "agent_message": response.get("message", ""),
                        "ask_attribute": response.get("ask_attribute"),
                        "usage": response.get("usage", {}),
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
                        "semantic_ranker": trace.get("semantic_ranker", {}),
                        "ranks": {
                            stage: _rank(values, target)
                            for stage, values in stage_values.items()
                        },
                        "recommendations": recommendations,
                    }
                )
                if turn == MAX_TURNS:
                    break
                override = effective.get("behavior", {}).get("override") or {}
                if not override_applied and turn + 1 == int(override.get("turn", 3)):
                    override_applied = True
                    new_value = str(override.get("new_value", ""))
                    if new_value:
                        disclosed.add(new_value)
                    user_message = str(
                        override.get(
                            "message",
                            "Actually, please ignore my earlier preference.",
                        )
                    )
                else:
                    user_message, boundary_used = customer_reply(
                        effective,
                        response.get("ask_attribute"),
                        disclosed,
                        boundary_used,
                    )
            if replay_hit:
                raise RuntimeError(
                    f"trace replay drifted from source miss and hit the target: {sample_id}"
                )

            eligible_turns = _eligible(turns)
            reason = _failure_reason(turns)
            asked = [
                str(turn["ask_attribute"])
                for turn in turns
                if turn["ask_attribute"] is not None
            ]
            duplicate_questions = sorted(
                attribute for attribute, count in Counter(asked).items() if count > 1
            )
            target_product = products[target]
            category_values = target_product.get("categories") or []
            sessions.append(
                {
                    "sample_id": sample_id,
                    "scenario_type": sample["scenario_type"],
                    "target": target,
                    "target_summary": {
                        "title": str(target_product.get("title") or ""),
                        "category": " > ".join(str(value) for value in category_values),
                        "price": target_product.get("price"),
                        "store": str(target_product.get("store") or ""),
                    },
                    "failure_reason": reason,
                    "suggested_action": _failure_suggestion(reason),
                    "all_turn_best_ranks": _best_ranks(turns),
                    "best_ranks": _best_ranks(eligible_turns),
                    "first_recall_turn": _first_recall_turn(eligible_turns),
                    "question_audit": {
                        "asked_attributes": asked,
                        "duplicate_attributes": duplicate_questions,
                        "unique_question_count": len(set(asked)),
                    },
                    "turns": turns,
                }
            )
            agent.sessions.pop(session_id, None)
            agent.response_cache.pop(session_id, None)
            agent.traces.pop(session_id, None)
    finally:
        agent.close()

    sessions.sort(
        key=lambda item: (
            SCENARIO_ORDER.index(item["scenario_type"])
            if item["scenario_type"] in SCENARIO_ORDER
            else len(SCENARIO_ORDER),
            _review_key(item),
        )
    )
    reason_counts = Counter(item["failure_reason"] for item in sessions)
    dataset_sha_after = sha256_file(dataset_path)
    catalog_sha_after = sha256_file(catalog_path)
    compliance_audit = _compliance_audit(
        sessions,
        catalog_ids,
        dataset_sha_before,
        dataset_sha_after,
        catalog_sha_before,
        catalog_sha_after,
    )
    source_metrics = {
        key: results[key]
        for key in (
            "hit_rate_at_10",
            "mrr",
            "mttc",
            "efficiency",
            "recommended_technical_score",
        )
    }
    report = {
        "source_results": str(results_path),
        "source_results_sha256": sha256_file(results_path),
        "source_run": source_run,
        "source_sample_count": len(source_sessions),
        "source_metrics": source_metrics,
        "dataset": str(dataset_path),
        "dataset_role": role,
        "dataset_sha256": dataset_sha_after,
        "catalog": str(catalog_path),
        "catalog_sha256": catalog_sha_after,
        "agent": args.agent,
        "failure_count": len(sessions),
        "override_failure_count": sum(
            item["scenario_type"] == "intent_override" for item in sessions
        ),
        "dense_status": {
            "enabled": agent.dense.enabled,
            "reason": agent.dense.reason,
            "backend": getattr(agent.dense, "backend", None),
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "scenario_summary": _scenario_summary(results, sessions, args.review_limit),
        "aggregate_audit": _aggregate_audit(sessions),
        "compliance_audit": compliance_audit,
        "sessions": sessions,
    }
    output = resolve_path(args.output)
    write_json(output, report)
    output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "failure_count",
                    "override_failure_count",
                    "reason_counts",
                    "scenario_summary",
                    "dense_status",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
