from __future__ import annotations

import math
import time

from solution.catalog import semantic_text
from solution.retrieval.base import Candidate


class OptionalCrossEncoder:
    """Top-N cross-encoder with an explicit switch, budget guard, and safe fallback."""

    def __init__(
        self,
        enabled: bool,
        model_name: str,
        top_n: int,
        weight: float,
        latency_budget_ms: float,
    ) -> None:
        self.enabled = False
        self.reason = "disabled by configuration"
        self.top_n = max(0, min(50, top_n))
        self.weight = max(0.0, min(1.0, weight))
        self.latency_budget_ms = max(0.0, latency_budget_ms)
        self.last_latency_ms: float | None = None
        if not enabled:
            return
        try:
            from flashrank import Ranker, RerankRequest
        except ImportError:
            self.reason = "install flashrank to run the cross-encoder ablation"
            return
        try:
            self.model = Ranker(model_name=model_name, cache_dir="artifacts/flashrank_cache", max_length=384)
            self.request_class = RerankRequest
        except Exception as exc:
            self.reason = f"cross-encoder initialization failed: {type(exc).__name__}"
            return
        self.enabled = True
        self.reason = "ready"

    def rerank(self, candidates: list[Candidate], query: str, products: dict[str, dict]) -> list[Candidate]:
        if not self.enabled or not candidates or not query.strip() or self.top_n == 0:
            return candidates
        head = candidates[: self.top_n]
        passages = [
            {"id": item.parent_asin, "text": semantic_text(products[item.parent_asin])}
            for item in head
        ]
        started = time.perf_counter()
        try:
            results = self.model.rerank(self.request_class(query=query, passages=passages))
        except Exception as exc:
            self.enabled = False
            self.reason = f"cross-encoder inference failed: {type(exc).__name__}"
            return candidates
        self.last_latency_ms = (time.perf_counter() - started) * 1000.0
        if self.last_latency_ms > self.latency_budget_ms:
            # Discard an over-budget call instead of partly applying a slow route.
            self.enabled = False
            self.reason = f"latency budget exceeded ({self.last_latency_ms:.1f} ms)"
            return candidates
        rescored: list[Candidate] = []
        scores = {str(item["id"]): float(item["score"]) for item in results}
        for candidate in head:
            value = scores.get(candidate.parent_asin, 0.0)
            probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))
            candidate.score = (1.0 - self.weight) * candidate.score + self.weight * probability
            rescored.append(candidate)
        rescored.sort(key=lambda item: (-item.score, item.parent_asin))
        return [*rescored, *candidates[self.top_n :]]

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "reason": self.reason,
            "top_n": self.top_n,
            "latency_budget_ms": self.latency_budget_ms,
            "last_latency_ms": self.last_latency_ms,
        }
