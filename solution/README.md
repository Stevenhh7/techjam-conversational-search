# Dual-track hybrid conversational search

This package is an independent submission candidate. It does not modify the official evaluator or the starter baseline.

## Pipeline

1. `catalog.py` normalizes immutable catalog fields and exposes exact/semantic representations.
2. `intent.py`, `constraint_parser.py`, and `routing.py` produce structured constraints and an executable Buying/ Browsing track decision.
3. `retrieval/bm25.py`, `retrieval/category.py`, and `retrieval/dense.py` provide independent keyword, category, metadata, and vector routes.
4. `pipeline.py` runs the precision Buying track or discovery Browsing track and keeps route evidence in memory.
5. `ranking/constraints.py` applies only reliable hard filters with a minimum-candidate relaxation guard; `ranking/reranker.py` scores the remainder.
6. Open-category Browsing requests can use deterministic category diversification.
7. `ranking/semantic.py` exposes a candidate-only semantic-ranking boundary. `llm/qwen.py` calls a local Ollama `qwen3.5:9b` model with structured output; it remains disabled by default until the local service is deployed.
8. `clarification.py` chooses a non-repeated attribute from candidate coverage, entropy, and expected reduction.
9. `agent.py` always returns current Top 10 and may simultaneously ask one allowed clarification.
10. `context/` distills bounded short/long-term evidence; `orchestration.py` compiles a per-turn Context Program, revises it after the sparse probe, and feeds Strategy Outcome back into the next turn.

## Multi-turn dialogue strategy

- `state_machine.py` records explicit dialogue phases and transition reasons.
- `SessionState.slot_store` is the active structured view; `slot_history` records add, replace, reset, and category rewrite operations.
- Full intent override clears stale preference slots, exclusions, and budget; attribute-level corrections replace only the affected slot.
- `pipeline.probe()` runs keyword/category/metadata retrieval before the expensive Dense/semantic stages.
- `generality.py` detects a genuinely open discovery request from query specificity, active slots, candidate count, and route saturation.
- Only an over-general request with a remaining clarification option cuts off Dense/LLM. It still returns sparse provisional Top 10 and a structured proactive prompt.
- Once the reply adds a slot, the next turn returns to the full vector and SemanticRanker path.
- Long-term learning requires an explicit external `profile_id`; anonymous sessions never write cross-session memory.
- Current requests override conflicting long-term preferences. Repeated recommendations, real no-progress turns, user rejection, candidate shortage, Override, and LLM failures revise the next plan within fixed configuration bounds.

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

## Full BGE index on a Windows GPU

Keep the virtual environment, package cache, temporary files, model cache, and generated index on the same drive as this repository:

```powershell
.\scripts\setup_gpu_environment.ps1
.\.venv\Scripts\python.exe scripts\build_embeddings.py `
  --backend fastembed `
  --provider cuda `
  --batch-size 512 `
  --checkpoint-every 50000 `
  --cache-dir artifacts\fastembed_cache `
  --local-files-only
```

Omit `--local-files-only` only for the first model download. The completed artifact must report `complete_catalog: true`, `indexed_row_count: 50000`, and `build_provider: CUDAExecutionProvider`. `StrictBgeAgent` refuses partial, stale-catalog, wrong-model, missing-CUDA, or fallback artifacts.

Use the frozen development split for tuning comparisons:

```powershell
.\.venv\Scripts\python.exe -m experiments.verify_frozen_data
.\.venv\Scripts\python.exe -m experiments.run_experiment `
  --config experiments\configs\bge_dense_dev.json `
  --name bge_dense_dev `
  --dataset data\splits\dev.jsonl `
  --run-dir experiments\runs\bge_dense_dev
```

The on-disk matrix stays compact `float16`; `DenseRetriever` promotes it once to an in-memory `float32` BLAS matrix. This preserves exact rankings while avoiding NumPy's slow CPU `float16` matrix-vector path.

## Optional local Qwen3.5 semantic ranking

Ollama uses the official `qwen3.5:9b` model tag and listens on `http://127.0.0.1:11434` by default. After the model is installed and the service is running, enable the adapter explicitly:

```powershell
ollama pull qwen3.5:9b
python -c "from solution.agent import Agent; from solution.config import SolutionConfig; agent = Agent(config=SolutionConfig(semantic_ranker_enabled=True))"
```

The adapter sends only the current candidate set, requests a complete JSON-schema-constrained permutation, disables thinking, and uses temperature 0. Connection errors, timeouts, malformed JSON, duplicate IDs, missing IDs, or invented IDs fall back to deterministic ranking. It records error counts, success/fallback rates, token totals, and mean/P50/P95 latency. Two consecutive failures open a session-local circuit breaker. Configure the endpoint, timeout, keep-alive, context window, and output budget through the `semantic_ranker_*` fields in `SolutionConfig`.

The current dev150 ablation improved MRR but did not improve HR, slightly worsened MTTC, had a 12.36% fallback rate, and took about 24.48 times as long as the deterministic Context Programming agent. Therefore Qwen remains an explicitly enabled experimental capability, not the default production path. See `docs/QWEN35_CONTEXT_DEV_ABLATION_ZH.md` and `docs/DYNAMIC_CONTEXT_PROGRAMMING_ZH.md`.

## Review invariants

- `parent_asin` values only come from the read-only catalog.
- The evaluator is never imported into solution logic and is not modified.
- Ranking is deterministic for the same catalog, state, and artifacts.
- Every recommendation is deduplicated and capped by `top_k`.
- `ask_attribute` is either an allowed value or `None`, and is not repeated in a session.
- No API key, online LLM, remote database, or generated product identifier is required; the optional LLM endpoint is local Ollama.
- The semantic ranker may only permute catalog-grounded input candidates; invalid output falls back to deterministic ranking.
- Cross-session profile writes require a non-empty external `profile_id`; anonymous sessions cannot leak preferences into another session.
- Context Programs are immutable per-turn plans and cannot exceed shared configuration limits or modify source code/global configuration.
