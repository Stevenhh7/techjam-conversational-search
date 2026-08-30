from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SolutionConfig:
    """One place for retrieval, ranking, and dialogue policy knobs."""

    candidate_limit: int = 120
    dense_mode: str = "supplement"
    dense_supplement_limit: int = 60
    dense_supplement_weight: float = 0.45
    rrf_k: int = 60
    dense_model: str = "BAAI/bge-small-en-v1.5"
    dense_providers: tuple[str, ...] = ("CPUExecutionProvider",)
    dense_embeddings_path: Path = Path("artifacts/product_embeddings.npy")
    dense_metadata_path: Path = Path("artifacts/product_embeddings.meta.json")
    ask_until_turn: int = 7
    buying_weights: dict[str, float] = field(
        default_factory=lambda: {"bm25": 1.2, "metadata": 1.0}
    )
    browsing_weights: dict[str, float] = field(
        default_factory=lambda: {"bm25": 0.9, "metadata": 0.8}
    )
    reranker_weights: dict[str, float] = field(
        default_factory=lambda: {
            "rrf": 0.31,
            "dense": 0.04,
            "lexical": 0.28,
            "exact": 0.18,
            "category": 0.10,
            "profile": 0.03,
            "rating": 0.02,
            "popularity": 0.04,
        }
    )
    cross_encoder_enabled: bool = False
    cross_encoder_model: str = "ms-marco-MiniLM-L-12-v2"
    cross_encoder_top_n: int = 30
    cross_encoder_weight: float = 0.15
    cross_encoder_latency_budget_ms: float = 2500.0
