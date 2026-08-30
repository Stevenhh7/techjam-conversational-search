from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from datetime import datetime, timezone

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from experiments.common import (
    REGISTRY_PATH,
    RUNS_DIR,
    append_jsonl,
    compact_metrics,
    git_metadata,
    load_agent,
    read_json,
    relative_to_root,
    resolve_path,
    safe_name,
    sha256_file,
    write_failures_csv,
    write_json,
)
from experiments.frozen import frozen_role, verify_frozen_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an Agent with the unmodified official evaluator")
    parser.add_argument("--config", help="Optional JSON config; explicit CLI values take precedence")
    parser.add_argument("--name")
    parser.add_argument("--agent")
    parser.add_argument("--catalog")
    parser.add_argument("--dataset")
    parser.add_argument("--notes")
    parser.add_argument("--run-dir", help="Optional explicit output directory")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--final-eval",
        action="store_true",
        help="Explicitly authorize one evaluation on a frozen holdout/public dataset",
    )
    return parser.parse_args()


def merged_config(args: argparse.Namespace) -> dict:
    config = read_json(args.config) if args.config else {}
    for key in ("name", "agent", "catalog", "dataset", "notes"):
        value = getattr(args, key)
        if value is not None:
            config[key] = value
    defaults = {
        "name": "experiment",
        "agent": "starter.agent:Agent",
        "catalog": "data/catalog.jsonl",
        "dataset": "data/public_set.jsonl",
        "notes": "",
    }
    return {**defaults, **config}


def main() -> None:
    args = parse_args()
    config = merged_config(args)
    name = safe_name(str(config["name"]))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = resolve_path(args.run_dir) if args.run_dir else RUNS_DIR / f"{timestamp}_{name}"
    if run_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"run directory already exists: {run_dir}; pass --overwrite to replace it")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    catalog_path = resolve_path(config["catalog"])
    dataset_path = resolve_path(config["dataset"])
    if not catalog_path.is_file():
        raise SystemExit(f"catalog not found: {catalog_path}")
    if not dataset_path.is_file():
        raise SystemExit(f"dataset not found: {dataset_path}")
    frozen_errors = verify_frozen_path(dataset_path)
    if frozen_errors:
        raise SystemExit("frozen dataset verification failed:\n- " + "\n- ".join(frozen_errors))
    role = frozen_role(dataset_path)
    if str(config.get("phase", "evaluation")) == "tuning" and role == "final_only" and not args.final_eval:
        raise SystemExit("refusing tuning run on frozen holdout/public data; pass --final-eval for final validation")

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    agent_class = load_agent(str(config["agent"]))
    samples = load_jsonl(dataset_path)
    catalog_ids, categories, products = catalog_index(catalog_path)
    agent = agent_class(catalog_path)
    try:
        results = evaluate(agent, samples, catalog_ids, categories, products)
        agent_status = {
            "dense": {
                "enabled": agent.dense.enabled,
                "reason": agent.dense.reason,
                "backend": getattr(agent.dense, "backend", None),
            } if hasattr(agent, "dense") else None,
            "cross_encoder": agent.cross_encoder.status() if hasattr(agent, "cross_encoder") else None,
            "semantic_ranker": agent.semantic_ranker.status() if hasattr(agent, "semantic_ranker") else None,
        }
    finally:
        close = getattr(agent, "close", None)
        if callable(close):
            close()
    elapsed_seconds = time.perf_counter() - started
    finished_at = datetime.now(timezone.utc)

    metadata = {
        "name": name,
        "agent": config["agent"],
        "catalog": relative_to_root(catalog_path),
        "catalog_sha256": sha256_file(catalog_path),
        "dataset": relative_to_root(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "notes": config.get("notes", ""),
        "phase": "final" if args.final_eval else config.get("phase", "evaluation"),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "python": sys.version,
        "platform": platform.platform(),
        "agent_status": agent_status,
        "git": git_metadata(),
    }
    summary = {**metadata, "metrics": compact_metrics(results)}
    write_json(run_dir / "config.json", config)
    write_json(run_dir / "metadata.json", metadata)
    write_json(run_dir / "results.json", results)
    write_json(run_dir / "summary.json", summary)
    write_failures_csv(run_dir / "failures.csv", results)
    append_jsonl(
        REGISTRY_PATH,
        {
            "name": name,
            "run_dir": relative_to_root(run_dir),
            "agent": config["agent"],
            "dataset": relative_to_root(dataset_path),
            "elapsed_seconds": metadata["elapsed_seconds"],
            **compact_metrics(results),
        },
    )
    print(json.dumps({"run_dir": relative_to_root(run_dir), **compact_metrics(results)}, indent=2))


if __name__ == "__main__":
    main()
