# Baseline reproduction report

Run date: 2026-08-30 (Asia/Shanghai)  
Branch: `project4-experiment-framework`  
Agent: unmodified `starter.agent:Agent`  
Official evaluator: unmodified; worktree SHA256 matches `HEAD`

## Catalog integrity

- Release tag: `participant-kit`
- Compressed catalog SHA256: `07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8`
- Catalog products: 50,000
- Public sessions: 200
- Public-set SHA256: `571359a8a69014c43fc30d39c996c4a28e875dccc249dffc707358757beb16c0`

## Full public-set reproduction

| Metric | Organizer reference | Reproduced | Match |
|---|---:|---:|:---:|
| Hit Rate@10 | 0.125000 | 0.125000 | Yes |
| MRR | 0.068034 | 0.068034 | Yes |
| MTTC | 9.810000 | 9.810000 | Yes |
| Efficiency | 0.119000 | 0.119000 | Yes |
| TechnicalScore | 0.106710 | 0.106710 | Yes |

### Scenario metrics

| Scenario | Count | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| buying | 80 | 0.237500 | 0.126508 | 8.625000 |
| browsing | 80 | 0.025000 | 0.004514 | 10.750000 |
| intent_override | 30 | 0.133333 | 0.104167 | 10.066667 |
| boundary | 10 | 0.000000 | 0.000000 | 11.000000 |

The weak baseline hits 25 of 200 sessions and misses 175. Browsing is the clearest first improvement target: only 2 of 80 browsing sessions hit the target.

## Deterministic dev/holdout split

The framework creates a scenario-stratified 150/50 split using seed `techjam-2026-v1`.

| Split | Count | Hit Rate@10 | MRR | MTTC | TechnicalScore |
|---|---:|---:|---:|---:|---:|
| Development | 150 | 0.113333 | 0.053304 | 9.906667 | 0.094524 |
| Holdout | 50 | 0.160000 | 0.112222 | 9.520000 | 0.143267 |

The holdout score is naturally noisier because it contains only 50 sessions. Tune on the development split and use holdout only for periodic regression checks; do not optimize directly against the holdout IDs.

## Reproduction commands

```bash
python -m experiments.split_public_set
python -m experiments.run_experiment --config experiments/configs/baseline.json
python -m unittest discover -s tests -v
```

See `experiments/README.md` for dev/holdout runs, comparisons, and failure reports.

