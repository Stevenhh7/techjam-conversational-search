from __future__ import annotations

import json
from pathlib import Path

from experiments.common import ROOT, sha256_file


MANIFEST_PATH = ROOT / "experiments" / "frozen_datasets.json"


def load_manifest() -> dict[str, dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def verify_manifest() -> list[str]:
    errors: list[str] = []
    for name, entry in load_manifest().items():
        path = ROOT / entry["path"]
        if not path.is_file():
            if entry.get("optional_generated"):
                continue
            errors.append(f"{name}: missing {path}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != entry["sha256"]:
            errors.append(f"{name}: SHA256 mismatch ({actual_hash})")
        with path.open(encoding="utf-8") as handle:
            count = sum(bool(line.strip()) for line in handle)
        if count != int(entry["sample_count"]):
            errors.append(f"{name}: sample count mismatch ({count})")
    return errors


def frozen_role(path: Path) -> str | None:
    resolved = path.resolve()
    for entry in load_manifest().values():
        if (ROOT / entry["path"]).resolve() == resolved:
            return str(entry["role"])
    return None


def verify_frozen_path(path: Path) -> list[str]:
    resolved = path.resolve()
    for name, entry in load_manifest().items():
        frozen_path = (ROOT / entry["path"]).resolve()
        if frozen_path != resolved:
            continue
        if not path.is_file():
            return [f"{name}: missing {path}"]
        actual_hash = sha256_file(path)
        errors = [] if actual_hash == entry["sha256"] else [f"{name}: SHA256 mismatch ({actual_hash})"]
        with path.open(encoding="utf-8") as handle:
            count = sum(bool(line.strip()) for line in handle)
        if count != int(entry["sample_count"]):
            errors.append(f"{name}: sample count mismatch ({count})")
        return errors
    return []
