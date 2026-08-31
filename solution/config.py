from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SolutionConfig:
    """One place for retrieval, ranking, and dialogue policy knobs."""

    candidate_limit: int = 120
    buying_threshold: float = 0.5
    buying_category_limit: int = 80
    buying_dense_limit: int = 120
    browsing_category_limit: int = 120
    browsing_dense_limit: int = 180
    buying_min_filtered_candidates: int = 30
    browsing_diversity_enabled: bool = True
    browsing_diversity_strength: float = 0.08
    semantic_ranker_top_n: int = 30
    semantic_ranker_enabled: bool = False
    semantic_ranker_backend: str = "ollama"
    semantic_ranker_model: str = "qwen3.5:9b"
    semantic_ranker_base_url: str = "http://127.0.0.1:11434"
    semantic_ranker_timeout_ms: float = 120000.0
    semantic_ranker_keep_alive: str = "10m"
    semantic_ranker_temperature: float = 0.0
    semantic_ranker_num_ctx: int = 8192
    semantic_ranker_num_predict: int = 1024
    semantic_ranker_circuit_breaker_failures: int = 2
    over_generality_cutoff_enabled: bool = True
    over_generality_max_query_terms: int = 4
    over_generality_max_active_slots: int = 0
    over_generality_min_unique_candidates: int = 160
    over_generality_min_saturated_routes: int = 2
    over_generality_ask_until_turn: int = 9
    dense_mode: str = "supplement"
    dense_supplement_limit: int = 60
    dense_supplement_weight: float = 0.45
    rrf_k: int = 60
    dense_model: str = "BAAI/bge-small-en-v1.5"
    dense_providers: tuple[str, ...] = ("CPUExecutionProvider",)
    dense_cache_dir: Path = Path("artifacts/fastembed_cache")
    dense_embeddings_path: Path = Path("artifacts/product_embeddings.npy")
    dense_metadata_path: Path = Path("artifacts/product_embeddings.meta.json")
    ask_until_turn: int = 7
    context_max_messages: int = 4
    context_max_candidates: int = 10
    context_max_preferences: int = 16
    context_max_summary_chars: int = 800
    context_max_outcomes: int = 4
    profile_promotion_sessions: int = 2
    profile_confidence_decay: float = 0.98
    orchestration_max_sparse_limit: int = 180
    orchestration_max_dense_limit: int = 240
    orchestration_low_candidate_threshold: int = 24
    orchestration_max_semantic_top_n: int = 30
    orchestration_novelty_penalty: float = 0.08
    orchestration_max_diversity_strength: float = 0.12
    buying_weights: dict[str, float] = field(
        default_factory=lambda: {"bm25": 1.2, "category": 0.18, "metadata": 1.0}
    )
    browsing_weights: dict[str, float] = field(
        default_factory=lambda: {"bm25": 0.9, "category": 0.08, "metadata": 0.8}
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
