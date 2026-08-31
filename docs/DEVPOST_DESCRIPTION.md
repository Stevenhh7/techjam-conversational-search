# ContextCart — Devpost Submission Copy

> Replace the two bracketed links and confirm the team-contribution sentence
> before pasting this page into Devpost.

- **Public GitHub:** `[ADD FINAL PUBLIC GITHUB URL]`
- **Public YouTube demo:** `[ADD FINAL YOUTUBE URL]`

## Tagline

An adaptive, offline-capable shopping agent that changes its retrieval and
clarification strategy as customer intent evolves.

## Inspiration

E-commerce search often assumes that a shopper already knows what to type. Real
shopping conversations are less orderly: someone may begin with “show me some
ideas,” add a weather requirement later, reject the first results, and then
switch to a specific product and budget. A static keyword query cannot represent
that changing decision process.

ContextCart was built around a different idea: context should be an executable
program, not just text appended to a prompt. Every turn should update an explicit
state, distill only the evidence that still matters, and select the cheapest
retrieval and dialogue strategy that fits the current intent.

## What it does

ContextCart is a next-generation conversational product-search agent for the
frozen 50,000-product Amazon Reviews 2023 Clothing, Shoes and Jewelry catalog.
It returns up to ten valid catalog products on every turn while optionally asking
one structured clarification question.

The system has two primary tracks:

- **Buying / Precision:** locks reliable material, category, price, and other
  constraints, then relaxes them only when the candidate pool would otherwise
  collapse.
- **Browsing / Discovery:** supplements sparse retrieval with dense candidates
  and category diversity to support open-ended, cross-category exploration.

An over-general request triggers an early cutoff before expensive Dense or LLM
stages. The agent still returns provisional recommendations, but asks a
high-information question to help the shopper converge. When the next answer
adds a useful slot, the full retrieval path is restored.

Across turns, ContextCart accumulates structured preferences, supports full and
attribute-level intent overrides, tracks rejected results, and keeps anonymous
sessions isolated. With an explicit profile ID, repeated or explicitly remembered
preferences can enter a privacy-safe in-memory long-term profile; current-session
instructions always win conflicts.

## How we built it

Each request passes through the following in-memory pipeline:

1. A deterministic state machine extracts and mutates typed slots.
2. A bounded context distiller combines recent messages, current constraints,
   profile evidence, prior recommendations, and strategy outcomes.
3. An adaptive orchestrator compiles an immutable per-turn Context Program.
4. Independent BM25, category, metadata, and vector routes retrieve candidates.
5. Reciprocal Rank Fusion and a local reranker combine relevance, constraints,
   profile evidence, ratings, popularity, and discovery diversity.
6. An optional local Qwen3.5 stage may reorder only the supplied candidate set.
7. The agent returns Top-10 catalog IDs and one non-repeated clarification.
8. Candidate reduction, repetition, override, rejection, fallback, and LLM
   outcomes feed the next Context Program.

The default dense route uses a reproducible signed-hashing index. Full BGE support
is implemented with resumable index construction, catalog SHA256 validation,
CPU/CUDA provider checks, and safe degradation when files or dependencies are
unavailable. No external vector database is used.

The optional Ollama adapter uses `qwen3.5:9b` with temperature zero and structured
JSON output. The LLM cannot invent products: its output must be a complete,
duplicate-free permutation of known candidate ASINs. Invalid JSON, unknown IDs,
missing IDs, timeouts, or connection failures return the original deterministic
ranking. Two consecutive failures open a session-local circuit breaker.

## Measured results

On the frozen 150-session development split:

- **Hit Rate@10:** 0.920000
- **MRR:** 0.607254
- **MTTC:** 4.360000 turns
- **Efficiency:** 0.664000
- **TechnicalScore:** 0.774976
- **End-to-end elapsed time:** 196.13 seconds

The result is tied to dataset SHA256
`c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a`
and catalog SHA256
`da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`.
These are development metrics and are not presented as a prediction of the
organizer's private 800 sessions.

We also completed a full Qwen3.5 dev150 ablation. Qwen improved MRR to 0.620931,
but did not improve Hit Rate, slightly worsened MTTC to 4.38, fell back on 12.36%
of requests, and made the run 24.48 times slower. We therefore kept Qwen as a
fully implemented optional capability instead of enabling it in the default
submission. For us, declining a more complicated model when it failed a measured
deployment gate is part of the engineering result.

## Challenges we ran into

The hardest challenge was balancing recall, precision, and conversation length
without leaking target information from the public evaluator. Increasing Dense
influence could recover candidates but also displace exact sparse matches. Hard
price filtering looked attractive until we audited the catalog's incomplete price
coverage. We introduced conservative relaxation guards and separated retrieval
membership from reranking influence.

Intent override was another difficult edge case. Resetting too much discards a
valid budget; resetting too little leaves stale material or category preferences.
We implemented auditable full, category, and attribute-level mutations rather
than treating “actually” as another query token.

Finally, local LLM integration required strict failure handling. A syntactically
valid answer can still duplicate one candidate or omit another. Catalog-grounded
permutation validation and deterministic fallback were necessary before the
model could safely enter the pipeline.

## Accomplishments that we are proud of

- One default offline evaluator command runs the final Agent without changing the
  organizer's evaluator.
- Every recommendation is catalog-grounded, unique, deterministic, and capped by
  the requested Top-K.
- The same Agent handles open discovery, precise buying, preference accumulation,
  boundary answers, rejection, and abrupt intent override.
- Dense and LLM paths have explicit integrity gates and safe degradation.
- The experiment harness records code state, hashes, latency, scenario metrics,
  token usage, and failure artifacts.
- A lightweight repository-native web page makes intent, routes, context,
  constraints, and Top-10 results visible without putting UI code into the Agent.

## What we learned

More model calls do not automatically create a better agent. Dynamic context is
most valuable when it changes executable decisions: which routes run, whether a
constraint is hard, whether diversity is useful, whether to ask a question, and
when a costly model should be skipped. We also learned that fallback behavior
must be evaluated as a first-class path rather than documented as an exception.

## What's next

We would quantize or ANN-index the full BGE matrix, distill the semantic ranker
into a faster local scorer, improve typed category and price extraction from
audited failures, and add encrypted revocable profile persistence with explicit
consent. After freezing all weights, we would run one confirmation on a newly
created unseen split.

## Built with

- Python, SQLite FTS5, NumPy
- FastEmbed and ONNX Runtime
- FlashRank
- Ollama and Qwen3.5 9B
- HTML/CSS/JavaScript and Python's standard-library HTTP server
- VS Code and Git

## Data and resources

The frozen competition catalog and sessions are derived from
[Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) by McAuley Lab,
UCSD. We use only text and structured metadata from the organizer's participant
kit. The repository does not publish the 50K catalog, private evaluation data,
model weights, API keys, or credentials.

## Team contributions

This submission is currently documented as a solo project. The repository owner
implemented the architecture, retrieval and ranking pipeline, dialogue state,
context programming, experiments, tests, documentation, and demo integration.
If the final Devpost team contains additional members, replace this paragraph
with exact names and contribution boundaries before submission.
