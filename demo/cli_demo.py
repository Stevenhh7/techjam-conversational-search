from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from solution.agent import Agent  # noqa: E402


DEFAULT_MESSAGES = (
    "Show me some ideas.",
    "For that, what matters is: waterproof.",
    "Actually, ignore my earlier preference. What I need is: "
    "material: leather; category: shoes; under $100.",
)


def run(catalog: Path, profile_id: str) -> None:
    agent = Agent(catalog, diagnostics=True)
    session_id = "contextcart-cli-demo"
    profile = {"profile_id": profile_id} if profile_id else {}
    agent.reset(session_id, profile)
    try:
        for turn, message in enumerate(DEFAULT_MESSAGES, start=1):
            response = agent.respond(session_id, message, turn, top_k=10)
            trace = agent.get_trace(session_id)[-1]
            track = str(trace["routing"]["track"]).upper()
            context = trace["distilled_context"]["summary"]
            program_reasons = ", ".join(trace["context_program"]["reasons"])
            print(f"\n=== Turn {turn}/10 · {track} ===")
            print(f"User: {message}")
            print(f"Agent: {response['message']}")
            print(
                "Strategy: "
                f"candidates={trace['strategy_outcome']['unique_candidate_count']}, "
                f"cutoff={trace['retrieval_cutoff']}, "
                f"ask={response['ask_attribute'] or 'none'}"
            )
            print(f"Context: {context}")
            print(f"Program reasons: {program_reasons}")
            print("Top 10:")
            for rank, item in enumerate(response["recommendations"], start=1):
                parent_asin = item["parent_asin"]
                product = agent.products[parent_asin]
                title = str(product.get("title") or "(untitled)")
                print(f"  {rank:>2}. {parent_asin} · {title[:100]}")
    finally:
        agent.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic three-turn ContextCart demo.")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--profile-id", default="")
    args = parser.parse_args()
    catalog = Path(args.catalog)
    if not catalog.is_file():
        raise SystemExit(f"catalog not found: {catalog}")
    run(catalog, args.profile_id.strip()[:128])


if __name__ == "__main__":
    main()
