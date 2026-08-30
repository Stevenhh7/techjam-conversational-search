# Steps 3-10 implementation

This package is an independent submission candidate. It does not modify the official evaluator or the starter baseline.

## Pipeline

1. `catalog.py` normalizes immutable catalog fields and exposes exact/semantic representations.
2. `retrieval/bm25.py` builds weighted FTS5 BM25 and a metadata-heavy route.
3. `retrieval/dense.py` loads an offline dense matrix. The reproducible CPU default is signed feature hashing; `--backend fastembed` builds BGE neural embeddings.
4. `retrieval/fusion.py` merges routes with mode-aware reciprocal-rank fusion.
5. `state.py` accumulates session constraints and removes stale preferences on override.
6. `intent.py` estimates buying/browsing intent with deterministic, inspectable rules.
7. `ranking/constraints.py` applies only reliable hard filters; `ranking/reranker.py` scores the remainder.
8. `clarification.py` chooses a non-repeated attribute from candidate coverage, entropy, and expected reduction.
9. `agent.py` always returns current Top 10 and may simultaneously ask one allowed clarification.

## Reproduce

```powershell
python scripts/analyze_catalog.py
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-solution.txt
.\.venv\Scripts\python.exe scripts/build_embeddings.py
# Optional neural index on a suitable machine:
.\.venv\Scripts\python.exe scripts/build_embeddings.py --backend fastembed
.\.venv\Scripts\python.exe -m experiments.run_experiment --config experiments/configs/hybrid_steps_3_10.json
python -m unittest discover -v
```

If the dense artifact or `fastembed` dependency is unavailable, `DenseRetriever` reports itself disabled and the agent safely runs the BM25 + metadata + state pipeline.

## Review invariants

- `parent_asin` values only come from the read-only catalog.
- The evaluator is never imported into solution logic and is not modified.
- Ranking is deterministic for the same catalog, state, and artifacts.
- Every recommendation is deduplicated and capped by `top_k`.
- `ask_attribute` is either an allowed value or `None`, and is not repeated in a session.
- No API key, online LLM, remote database, or generated product identifier is required.
