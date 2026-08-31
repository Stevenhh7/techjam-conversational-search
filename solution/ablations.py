from __future__ import annotations

from pathlib import Path

from solution.agent import Agent
from solution.config import SolutionConfig


class LegacyDoubleDenseAgent(Agent):
    """Reproduce the pre-audit hybrid where dense contributed in both stages."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl", diagnostics: bool = False) -> None:
        config = SolutionConfig(
            dense_mode="rrf",
            buying_weights={"bm25": 1.2, "dense": 0.7, "metadata": 1.0},
            browsing_weights={"bm25": 0.7, "dense": 1.2, "metadata": 0.8},
            reranker_weights={
                "rrf": 0.30,
                "dense": 0.20,
                "lexical": 0.22,
                "exact": 0.12,
                "category": 0.09,
                "profile": 0.04,
                "rating": 0.03,
                "popularity": 0.0,
            },
        )
        super().__init__(catalog_path, config=config, diagnostics=diagnostics)


class CrossEncoderTop30Agent(Agent):
    """Opt-in Top-30 cross-encoder ablation; production Agent keeps it off."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl", diagnostics: bool = False) -> None:
        config = SolutionConfig(cross_encoder_enabled=True, cross_encoder_top_n=30)
        super().__init__(catalog_path, config=config, diagnostics=diagnostics)


class OllamaQwenAgent(Agent):
    """Explicit opt-in Qwen3.5 ablation; the production Agent keeps LLM ranking off."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl", diagnostics: bool = False) -> None:
        config = SolutionConfig(semantic_ranker_enabled=True)
        super().__init__(catalog_path, config=config, diagnostics=diagnostics)


class StrictBgeAgent(Agent):
    """BGE ablation that refuses to masquerade as a fallback hashing/sparse run."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl", diagnostics: bool = False) -> None:
        config = SolutionConfig(
            dense_embeddings_path=Path("artifacts/bge_product_embeddings.npy"),
            dense_metadata_path=Path("artifacts/bge_product_embeddings.meta.json"),
            dense_providers=("CUDAExecutionProvider",),
        )
        super().__init__(catalog_path, config=config, diagnostics=diagnostics)
        if not self.dense.enabled or getattr(self.dense, "backend", None) != "fastembed":
            reason = self.dense.reason
            self.close()
            raise RuntimeError(f"strict BGE ablation requires a complete matching neural index: {reason}")
