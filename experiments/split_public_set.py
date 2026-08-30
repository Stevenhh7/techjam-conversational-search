from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from experiments.common import ROOT, relative_to_root, resolve_path, sha256_file, write_json


def stable_key(sample_id: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}\0{sample_id}".encode("utf-8")).hexdigest()


def stratified_split(samples: list[dict], holdout_fraction: float, seed: str) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["scenario_type"])].append(sample)

    dev: list[dict] = []
    holdout: list[dict] = []
    for scenario in sorted(grouped):
        ordered = sorted(grouped[scenario], key=lambda item: stable_key(str(item["sample_id"]), seed))
        holdout_count = max(1, round(len(ordered) * holdout_fraction))
        holdout.extend(ordered[:holdout_count])
        dev.extend(ordered[holdout_count:])
    return sorted(dev, key=lambda item: str(item["sample_id"])), sorted(
        holdout, key=lambda item: str(item["sample_id"])
    )


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def counts(rows: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(str(row["scenario_type"]) for row in rows).items()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create deterministic scenario-stratified public splits")
    parser.add_argument("--source", default="data/public_set.jsonl")
    parser.add_argument("--output-dir", default="data/splits")
    parser.add_argument("--holdout-fraction", type=float, default=0.25)
    parser.add_argument("--seed", default="techjam-2026-v1")
    args = parser.parse_args()
    if not 0.05 <= args.holdout_fraction <= 0.5:
        raise SystemExit("--holdout-fraction must be between 0.05 and 0.5")

    source = resolve_path(args.source)
    samples = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    dev, holdout = stratified_split(samples, args.holdout_fraction, args.seed)
    output_dir = resolve_path(args.output_dir)
    dev_path = output_dir / "dev.jsonl"
    holdout_path = output_dir / "holdout.jsonl"
    write_jsonl(dev_path, dev)
    write_jsonl(holdout_path, holdout)
    manifest = {
        "source": relative_to_root(source),
        "source_sha256": sha256_file(source),
        "seed": args.seed,
        "holdout_fraction": args.holdout_fraction,
        "total_count": len(samples),
        "dev": {"path": relative_to_root(dev_path), "count": len(dev), "scenario_counts": counts(dev)},
        "holdout": {
            "path": relative_to_root(holdout_path),
            "count": len(holdout),
            "scenario_counts": counts(holdout),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

