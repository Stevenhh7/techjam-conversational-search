from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SolutionConfig:
    """One place for retrieval, ranking, and dialogue policy knobs."""

    candidate_limit: int = 120
    rrf_k: int = 60
    dense_model: str = "BAAI/bge-small-en-v1.5"
    dense_embeddings_path: Path = Path("artifacts/product_embeddings.npy")
    dense_metadata_path: Path = Path("artifacts/product_embeddings.meta.json")
    ask_until_turn: int = 7
    buying_weights: dict[str, float] = field(
        default_factory=lambda: {"bm25": 1.2, "dense": 0.7, "metadata": 1.0}
    )
    browsing_weights: dict[str, float] = field(
        default_factory=lambda: {"bm25": 0.7, "dense": 1.2, "metadata": 0.8}
    )

