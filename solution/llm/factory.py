from __future__ import annotations

from solution.config import SolutionConfig
from solution.llm.base import SemanticRanker
from solution.llm.disabled import DisabledSemanticRanker
from solution.llm.qwen import OllamaQwenSemanticRanker


def create_semantic_ranker(config: SolutionConfig) -> SemanticRanker:
    if not config.semantic_ranker_enabled or config.semantic_ranker_backend == "disabled":
        return DisabledSemanticRanker(config.semantic_ranker_model)
    if config.semantic_ranker_backend in {"ollama", "qwen", "qwen-ollama"}:
        return OllamaQwenSemanticRanker(
            config.semantic_ranker_model,
            config.semantic_ranker_base_url,
            config.semantic_ranker_timeout_ms,
            config.semantic_ranker_keep_alive,
            config.semantic_ranker_temperature,
            config.semantic_ranker_num_ctx,
            config.semantic_ranker_num_predict,
        )
    return DisabledSemanticRanker(
        config.semantic_ranker_model,
        f"unsupported semantic ranker backend: {config.semantic_ranker_backend}",
    )
