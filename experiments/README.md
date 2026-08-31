# Experiment framework

This directory wraps the organizer's unmodified evaluator with reproducible run metadata, deterministic public-data splits, failure exports, and run comparisons.

## 1. Generate the dev/holdout split

```bash
python -m experiments.split_public_set
```

The default split is scenario-stratified: 150 development sessions and 50 holdout sessions. Generated split files are ignored by Git and can always be recreated from the manifest seed.

## 2. Run an experiment

Full public baseline:

```bash
python -m experiments.run_experiment --config experiments/configs/baseline.json
```

Development split:

```bash
python -m experiments.run_experiment \
  --name weak-bm25-dev \
  --agent starter.baseline_agent:Agent \
  --dataset data/splits/dev.jsonl
```

Holdout split:

```bash
python -m experiments.run_experiment \
  --name weak-bm25-holdout \
  --agent starter.baseline_agent:Agent \
  --dataset data/splits/holdout.jsonl
```

Each run writes:

- `config.json`: requested experiment configuration
- `metadata.json`: hashes, timestamps, platform, elapsed time, and Git state
- `results.json`: complete official evaluator output
- `summary.json`: metadata plus aggregate/scenario metrics
- `failures.csv`: one row for every missed session

The global `experiments/registry.jsonl` is a local, append-only index of runs.

## 3. Compare experiments

```bash
python -m experiments.compare_runs \
  experiments/runs/<baseline-run> \
  experiments/runs/<candidate-run>
```

For `mttc`, a positive `improvement` means fewer turns. For every other metric, positive means a larger score.

## 4. Summarize failures

```bash
python -m experiments.analyze_failures experiments/runs/<run>
```

## Integrity rules

- Do not edit `evaluator/local_evaluator.py`.
- Do not edit labels in `data/public_set.jsonl`.
- Tune on `data/splits/dev.jsonl`; use holdout only for periodic checks.
- Record every reported score with the dataset hash and Git commit stored in the run metadata.
