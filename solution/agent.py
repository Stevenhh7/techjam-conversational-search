from __future__ import annotations

from pathlib import Path

from solution.catalog import load_documents
from solution.clarification import choose_attribute, question_for
from solution.config import SolutionConfig
from solution.query_builder import build_query
from solution.ranking.reranker import rerank
from solution.retrieval.bm25 import BM25Retriever
from solution.retrieval.dense import DenseRetriever
from solution.retrieval.fusion import reciprocal_rank_fusion
from solution.schemas import SessionState
from solution.state import update_state


class Agent:
    """Deterministic hybrid agent compatible with the official API contract."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        self.config = SolutionConfig()
        repository_root = self.catalog_path.resolve().parent.parent
        embeddings_path = self.config.dense_embeddings_path
        metadata_path = self.config.dense_metadata_path
        if not embeddings_path.is_absolute():
            embeddings_path = repository_root / embeddings_path
        if not metadata_path.is_absolute():
            metadata_path = repository_root / metadata_path
        self.documents = load_documents(self.catalog_path)
        self.products = {doc.parent_asin: doc.raw for doc in self.documents}
        self.bm25 = BM25Retriever(self.documents)
        self.dense = DenseRetriever(
            embeddings_path,
            metadata_path,
            self.config.dense_model,
            self.catalog_path,
        )
        self.sessions: dict[str, SessionState] = {}
        self.popular = sorted(
            self.documents,
            key=lambda doc: (-(doc.raw.get("rating_number") or 0), doc.parent_asin),
        )

    def reset(self, session_id: str, user_profile: dict) -> None:
        self.sessions[session_id] = SessionState(session_id=session_id, user_profile=user_profile or {})

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        if session_id not in self.sessions:
            raise RuntimeError("reset must be called before respond")
        state = update_state(self.sessions[session_id], user_message, turn)
        query = build_query(state)
        limit = self.config.candidate_limit
        routes = {
            "bm25": self.bm25.search(query.lexical, limit),
            "metadata": self.bm25.metadata_search(query.lexical, limit),
            "dense": self.dense.search(query.semantic, limit),
        }
        weights = self.config.buying_weights if state.buying_probability >= 0.5 else self.config.browsing_weights
        fused = reciprocal_rank_fusion(routes, weights, self.config.rrf_k)
        ranked = rerank(fused, self.products, query, state)
        ranked_ids = [item.parent_asin for item in ranked]
        if len(ranked_ids) < top_k:
            seen = set(ranked_ids)
            ranked_ids.extend(doc.parent_asin for doc in self.popular if doc.parent_asin not in seen)
        recommendations = ranked_ids[:top_k]
        attribute = choose_attribute(state, ranked_ids, self.products) if turn <= self.config.ask_until_turn else None
        if attribute:
            state.asked_attributes.add(attribute)
        state.previous_recommendations = recommendations
        question = question_for(attribute)
        message = "Here are the strongest current matches."
        if question:
            message += " " + question
        return {
            "message": message,
            "ask_attribute": attribute,
            "recommendations": [{"parent_asin": value} for value in recommendations],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    def close(self) -> None:
        if getattr(self, "bm25", None) is not None:
            self.bm25.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
