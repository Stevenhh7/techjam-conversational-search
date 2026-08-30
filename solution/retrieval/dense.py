from __future__ import annotations

import json
import hashlib
from collections import OrderedDict
from pathlib import Path

from solution.retrieval.base import Candidate
from solution.retrieval.hashing import hashing_vector


class DenseRetriever:
    """Optional BGE dense route. It degrades cleanly when artifacts/deps are absent."""

    def __init__(
        self,
        embeddings_path: Path,
        metadata_path: Path,
        model_name: str,
        catalog_path: Path | None = None,
        expected_count: int | None = None,
        providers: tuple[str, ...] = ("CPUExecutionProvider",),
        cache_dir: Path | None = None,
    ) -> None:
        self.enabled = False
        self.reason = "dense artifact not built"
        self.model_name = model_name
        self.cache: OrderedDict[tuple[str, int], tuple[tuple[str, float], ...]] = OrderedDict()
        self.cache_limit = 512
        if not embeddings_path.is_file() or not metadata_path.is_file():
            return
        try:
            import numpy as np
        except ImportError:
            self.reason = "install numpy to enable dense retrieval"
            return
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.reason = "dense metadata is unreadable"
            return
        if metadata.get("complete_catalog") is False:
            self.reason = "dense index is a partial smoke-test artifact"
            return
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
            if "CUDAExecutionProvider" in providers:
                try:
                    import onnxruntime as ort
                except ImportError:
                    self.reason = "install onnxruntime-gpu to use CUDA dense inference"
                    return
                if "CUDAExecutionProvider" not in ort.get_available_providers():
                    self.reason = "CUDAExecutionProvider is unavailable"
                    return
                try:
                    ort.preload_dlls()
                except Exception as exc:
                    self.reason = f"CUDA runtime preload failed: {type(exc).__name__}"
                    return
            try:
                self.encoder = TextEmbedding(
                    model_name=model_name,
                    providers=list(providers),
                    cache_dir=str(cache_dir) if cache_dir is not None else None,
                    local_files_only=True,
                )
            except Exception as exc:
                self.reason = f"dense model initialization failed: {type(exc).__name__}"
                return
        elif self.backend != "hashing":
            self.reason = f"unsupported dense backend: {self.backend}"
            return
        self.np = np
        try:
            self.dimension = int(metadata.get("dimension", 384))
            self.ids = [str(value) for value in metadata["parent_asins"]]
            self.matrix = np.load(embeddings_path, mmap_mode="r")
        except (KeyError, TypeError, ValueError, OSError):
            self.reason = "dense artifact contents are invalid"
            return
        if self.matrix.shape[0] != len(self.ids):
            self.reason = "dense index row count mismatch"
            return
        if expected_count is not None and len(self.ids) != expected_count:
            self.reason = "dense index does not cover the full catalog"
            return
        if expected_count is not None and int(metadata.get("catalog_row_count", expected_count)) != expected_count:
            self.reason = "dense metadata catalog row count mismatch"
            return
        # NumPy's CPU float16 matrix-vector path is substantially slower than
        # its float32 BLAS path. Keep the compact on-disk artifact, but promote
        # it once at startup for low-latency in-memory retrieval. The stored
        # values are unchanged, so rankings remain identical.
        self.search_matrix = np.asarray(self.matrix, dtype=np.float32)
        self.enabled = True
        self.reason = "ready"

    def search(self, query: str, limit: int) -> list[Candidate]:
        if not self.enabled or not query.strip():
            return []
        key = (query, limit)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.move_to_end(key)
            return [Candidate(parent_asin, score) for parent_asin, score in cached]
        if self.backend == "hashing":
            vector = hashing_vector(query, self.dimension)
        else:
            vector = next(iter(self.encoder.query_embed(query))).astype("float32")
        scores = self.search_matrix @ vector
        count = min(limit, len(self.ids))
        indices = self.np.argpartition(scores, -count)[-count:]
        indices = indices[self.np.argsort(scores[indices])[::-1]]
        cached = tuple((self.ids[int(index)], float(scores[int(index)])) for index in indices)
        self.cache[key] = cached
        self.cache.move_to_end(key)
        if len(self.cache) > self.cache_limit:
            self.cache.popitem(last=False)
        return [Candidate(parent_asin, score) for parent_asin, score in cached]
