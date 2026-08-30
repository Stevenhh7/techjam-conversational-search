from __future__ import annotations

import json
import hashlib
from pathlib import Path

from solution.retrieval.base import Candidate
from solution.retrieval.hashing import hashing_vector


class DenseRetriever:
    """Optional BGE dense route. It degrades cleanly when artifacts/deps are absent."""

    def __init__(self, embeddings_path: Path, metadata_path: Path, model_name: str, catalog_path: Path | None = None) -> None:
        self.enabled = False
        self.reason = "dense artifact not built"
        self.model_name = model_name
        if not embeddings_path.is_file() or not metadata_path.is_file():
            return
        try:
            import numpy as np
        except ImportError:
            self.reason = "install numpy to enable dense retrieval"
            return
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if catalog_path is not None and metadata.get("catalog_sha256"):
            digest = hashlib.sha256()
            with catalog_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != metadata["catalog_sha256"]:
                self.reason = "dense artifact was built from a different catalog"
                return
        self.backend = str(metadata.get("backend", "fastembed"))
        if self.backend == "fastembed":
            if metadata.get("model") != model_name:
                self.reason = "dense model and artifact metadata do not match"
                return
            try:
                from fastembed import TextEmbedding
            except ImportError:
                self.reason = "install fastembed to use the neural dense artifact"
                return
            self.encoder = TextEmbedding(model_name=model_name, providers=["CPUExecutionProvider"])
        elif self.backend != "hashing":
            self.reason = f"unsupported dense backend: {self.backend}"
            return
        self.np = np
        self.dimension = int(metadata.get("dimension", 384))
        self.ids = [str(value) for value in metadata["parent_asins"]]
        self.matrix = np.load(embeddings_path, mmap_mode="r")
        if self.matrix.shape[0] != len(self.ids):
            self.reason = "dense index row count mismatch"
            return
        self.enabled = True
        self.reason = "ready"

    def search(self, query: str, limit: int) -> list[Candidate]:
        if not self.enabled or not query.strip():
            return []
        if self.backend == "hashing":
            vector = hashing_vector(query, self.dimension)
        else:
            vector = next(iter(self.encoder.query_embed(query))).astype("float32")
        scores = self.matrix @ vector
        count = min(limit, len(self.ids))
        indices = self.np.argpartition(scores, -count)[-count:]
        indices = indices[self.np.argsort(scores[indices])[::-1]]
        return [Candidate(self.ids[int(index)], float(scores[int(index)])) for index in indices]
