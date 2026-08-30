from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from experiments.common import ROOT, relative_to_root, resolve_path, sha256_file, write_json


PROFILE_TAGS = (
    ("fit", "comfort", "durability"),
    ("material", "fit"),
    ("style", "comfort"),
    ("value", "durability", "quality"),
)


def stable_key(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}\0{value}".encode()).hexdigest()


def load_targets(path: Path) -> set[str]:
    targets: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                targets.add(str(row["ground_truth"]["parent_asin"]))
    return targets


def catalog_ids(path: Path) -> list[str]:
    values: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                values.append(str(json.loads(line)["parent_asin"]))
    return values


def scenarios(count: int, seed: str) -> list[str]:
    buying = round(count * 0.40)
    browsing = round(count * 0.40)
    override = round(count * 0.15)
    boundary = count - buying - browsing - override
    labels = ["buying"] * buying + ["browsing"] * browsing
    labels += ["intent_override"] * override + ["boundary"] * boundary
    return [label for _, label in sorted((stable_key(seed, f"scenario-{index}"), label) for index, label in enumerate(labels))]


def profile(seed: str, parent_asin: str) -> dict:
    value = int(stable_key(seed, parent_asin)[:8], 16)
    tags = PROFILE_TAGS[value % len(PROFILE_TAGS)]
    average = (1.0, 3.0, 4.0, 5.0)[(value // 7) % 4]
    style = "critical" if average <= 2 else "mixed" if average == 3 else "usually positive"
    frequency = ("1-2 prior purchases", "3-4 prior purchases", "5+ prior purchases")[(value // 13) % 3]
    tag_text = ", ".join(tags)
    return {
        "average_prior_rating": average,
        "preference_tags": list(tags),
        "purchase_frequency": frequency,
        "rating_style": style,
        "summary": f"Prior purchases emphasize {tag_text}; ratings are {style}.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a sealed catalog-synthetic final split with unseen targets")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--exclude", default="data/public_set.jsonl")
    parser.add_argument("--output", default="data/splits/final_bge_200.jsonl")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", default="techjam-2026-bge-final-v1")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.count < 20:
        raise SystemExit("--count must be at least 20")

    catalog_path = resolve_path(args.catalog)
    exclude_path = resolve_path(args.exclude)
    output_path = resolve_path(args.output)
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"sealed final already exists: {output_path}; refusing to overwrite")

    excluded = load_targets(exclude_path)
    candidates = [value for value in catalog_ids(catalog_path) if value not in excluded]
    selected = sorted(candidates, key=lambda value: stable_key(args.seed, value))[: args.count]
    if len(selected) != args.count or set(selected) & excluded:
        raise SystemExit("could not create a disjoint final target set")

    labels = scenarios(args.count, args.seed)
    rows = [
        {
            "category_bucket": "clothing",
            "difficulty_bucket": "sealed",
            "ground_truth": {"parent_asin": parent_asin},
            "sample_id": f"final_bge_{index:04d}",
            "scenario_type": labels[index - 1],
            "user_profile": profile(args.seed, parent_asin),
        }
        for index, parent_asin in enumerate(selected, 1)
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "dataset": relative_to_root(output_path),
        "dataset_sha256": sha256_file(output_path),
        "catalog": relative_to_root(catalog_path),
        "catalog_sha256": sha256_file(catalog_path),
        "excluded_dataset": relative_to_root(exclude_path),
        "excluded_dataset_sha256": sha256_file(exclude_path),
        "seed": args.seed,
        "sample_count": len(rows),
        "scenario_counts": dict(sorted(Counter(labels).items())),
        "target_overlap_with_excluded": len(set(selected) & excluded),
        "intent_cards_materialized": False,
        "warning": "Synthetic catalog-target evaluation; not a substitute for the organizer private set.",
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
