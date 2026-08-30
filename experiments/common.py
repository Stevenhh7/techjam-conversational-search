from __future__ import annotations

import csv
import hashlib
import importlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "experiments" / "runs"
REGISTRY_PATH = ROOT / "experiments" / "registry.jsonl"
SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def relative_to_root(path: str | Path) -> str:
    resolved = resolve_path(path).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with resolve_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    cleaned = SAFE_NAME_RE.sub("-", value.strip()).strip("-._")
    if not cleaned:
        raise ValueError("experiment name must contain a letter or number")
    return cleaned[:80]


def load_agent(spec: str) -> type:
    module_name, separator, class_name = spec.partition(":")
    if not separator or not module_name or not class_name:
        raise ValueError("agent must use module.path:ClassName syntax")
    module = importlib.import_module(module_name)
    agent_class = getattr(module, class_name)
    if not isinstance(agent_class, type):
        raise TypeError(f"{spec} did not resolve to a class")
    return agent_class


def git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=ROOT, check=False, capture_output=True, text=True
        )
        return completed.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD") or None,
        "branch": run("branch", "--show-current") or None,
        "dirty": bool(status),
        "status": status.splitlines(),
    }


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(resolve_path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: str | Path, value: Any) -> None:
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def write_failures_csv(path: str | Path, results: dict[str, Any]) -> None:
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ["sample_id", "scenario_type", "hit", "first_hit_turn", "best_rank", "reciprocal_rank"]
    failures = [session for session in results.get("sessions", []) if not session.get("hit")]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(failures)


def compact_metrics(results: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in results.items() if key != "sessions"}

