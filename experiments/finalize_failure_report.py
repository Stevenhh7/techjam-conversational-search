from __future__ import annotations

import argparse
import json

from evaluator.local_evaluator import catalog_index, load_jsonl
from experiments.common import resolve_path, sha256_file, write_json
from experiments.frozen import frozen_role, verify_frozen_path
from experiments.trace_failures import _aggregate_audit, _compliance_audit, _markdown


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Revalidate and render an existing failure trace without rerunning retrieval"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", help="Defaults to updating --input in place")
    args = parser.parse_args()

    input_path = resolve_path(args.input)
    if not input_path.is_file():
        raise SystemExit(f"failure trace not found: {input_path}")
    report = json.loads(input_path.read_text(encoding="utf-8"))
    dataset_path = resolve_path(report["dataset"])
    catalog_path = resolve_path(report["catalog"])
    results_path = resolve_path(report["source_results"])

    frozen_errors = verify_frozen_path(dataset_path)
    if frozen_errors:
        raise SystemExit("frozen dataset verification failed:\n- " + "\n- ".join(frozen_errors))
    if frozen_role(dataset_path) == "final_only":
        raise SystemExit("refusing to finalize a development failure report from final-only data")

    dataset_sha_before = sha256_file(dataset_path)
    catalog_sha_before = sha256_file(catalog_path)
    if dataset_sha_before != report["dataset_sha256"]:
        raise SystemExit("failure trace dataset SHA256 no longer matches")
    if catalog_sha_before != report["catalog_sha256"]:
        raise SystemExit("failure trace catalog SHA256 no longer matches")
    if sha256_file(results_path) != report["source_results_sha256"]:
        raise SystemExit("failure trace source results SHA256 no longer matches")

    source_results = json.loads(results_path.read_text(encoding="utf-8"))
    source_failed_ids = {
        str(item["sample_id"])
        for item in source_results.get("sessions", [])
        if not item.get("hit")
    }
    traced_ids = {str(item["sample_id"]) for item in report["sessions"]}
    dataset_ids = {str(item["sample_id"]) for item in load_jsonl(dataset_path)}
    if traced_ids != source_failed_ids or not traced_ids.issubset(dataset_ids):
        raise SystemExit("failure trace does not exactly cover the source run misses")

    catalog_ids, _, _ = catalog_index(catalog_path)
    dataset_sha_after = sha256_file(dataset_path)
    catalog_sha_after = sha256_file(catalog_path)
    report["aggregate_audit"] = _aggregate_audit(report["sessions"])
    report["compliance_audit"] = _compliance_audit(
        report["sessions"],
        catalog_ids,
        dataset_sha_before,
        dataset_sha_after,
        catalog_sha_before,
        catalog_sha_after,
    )
    output_path = resolve_path(args.output) if args.output else input_path
    write_json(output_path, report)
    output_path.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "failure_count": report["failure_count"],
                "aggregate_audit": report["aggregate_audit"],
                "compliance_audit": report["compliance_audit"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
