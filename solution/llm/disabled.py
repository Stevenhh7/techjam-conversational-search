from __future__ import annotations

from solution.llm.base import SemanticRankRequest, SemanticRankResult


class DisabledSemanticRanker:
    def __init__(self, model_name: str, reason: str = "disabled by configuration") -> None:
        self.model_name = model_name
        self.reason = reason

    def rank(self, request: SemanticRankRequest) -> SemanticRankResult:
        return SemanticRankResult(
            ordered_parent_asins=tuple(item.parent_asin for item in request.candidates),
            applied=False,
            reason=self.reason,
        )

    def status(self) -> dict[str, object]:
        return {
            "enabled": False,
            "backend": "disabled",
            "model": self.model_name,
            "reason": self.reason,
        }

    def close(self) -> None:
        return None
