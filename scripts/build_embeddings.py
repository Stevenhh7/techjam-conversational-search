from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solution.catalog import iter_catalog, semantic_text
from solution.retrieval.hashing import hashing_vector


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def encode_batch(backend: str, encoder: object, texts: list[str], dimension: int, batch_size: int) -> np.ndarray:
    if backend == "fastembed":
        values = list(encoder.passage_embed(texts, batch_size=batch_size))
        matrix = np.asarray(values, dtype=np.float32)
    else:
        matrix = np.asarray([hashing_vector(text, dimension) for text in texts], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix /= np.maximum(norms, 1e-12)
    return matrix.astype(np.float16)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a resumable, normalized product embedding index")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--backend", choices=("hashing", "fastembed"), default="hashing")
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument(
        "--cache-dir",
        default="artifacts/fastembed_cache",
        help="FastEmbed model cache; defaults to an E-drive project directory when the repository is on E:",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Require an already populated model cache and make no network requests",
    )
    parser.add_argument("--dimension", type=int, default=384)
    parser.add_argument("--output", help="Defaults to a backend-specific artifact path")
    parser.add_argument("--metadata", help="Defaults to a backend-specific artifact path")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--provider", choices=("cpu", "cuda", "auto"), default="auto")
    parser.add_argument("--checkpoint-every", type=int, default=1000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, help="Smoke-test row limit; partial indexes are never enabled by Agent")
    args = parser.parse_args()
    if args.batch_size <= 0 or args.checkpoint_every <= 0:
        raise SystemExit("--batch-size and --checkpoint-every must be positive")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive")

    default_stem = "bge_product_embeddings" if args.backend == "fastembed" else "product_embeddings"
    output = Path(args.output or f"artifacts/{default_stem}.npy")
    metadata_path = Path(args.metadata or f"artifacts/{default_stem}.meta.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    building_path = output.with_suffix(output.suffix + ".building")
    progress_path = metadata_path.with_suffix(metadata_path.suffix + ".progress.json")

    catalog_path = Path(args.catalog)
    all_products = list(iter_catalog(catalog_path))
    catalog_row_count = len(all_products)
    products = all_products[: args.limit] if args.limit else all_products
    digest = sha256(catalog_path)
    total = len(products)
    if not total:
        raise SystemExit("catalog contains no products")

    encoder: object = None
    selected_provider = "signed-hashing"
    if args.backend == "fastembed":
        from fastembed import TextEmbedding
        import onnxruntime as ort

        available = ort.get_available_providers()
        if args.provider == "cuda":
            if "CUDAExecutionProvider" not in available:
                raise SystemExit("CUDAExecutionProvider requested but unavailable; install requirements-gpu.txt")
            selected_provider = "CUDAExecutionProvider"
        elif args.provider == "auto" and "CUDAExecutionProvider" in available:
            selected_provider = "CUDAExecutionProvider"
        else:
            selected_provider = "CPUExecutionProvider"
        if selected_provider == "CUDAExecutionProvider":
            ort.preload_dlls()
        encoder = TextEmbedding(
            model_name=args.model,
            providers=[selected_provider],
            cache_dir=str(cache_dir),
            local_files_only=args.local_files_only,
        )

    expected = {
        "backend": args.backend,
        "model": args.model if args.backend == "fastembed" else "signed-hashing-unigram-bigram-v1",
        "catalog_sha256": digest,
        "target_row_count": total,
        "provider": selected_provider,
    }
    start = 0
    matrix: np.memmap | None = None
    if args.resume and progress_path.is_file() and building_path.is_file():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if any(progress.get(key) != value for key, value in expected.items()):
            raise SystemExit("resume checkpoint does not match backend/model/catalog/row count")
        start = int(progress.get("completed_rows", 0))
        matrix = np.lib.format.open_memmap(building_path, mode="r+")
        if matrix.shape[0] != total:
            raise SystemExit("resume matrix row count does not match checkpoint")

    for offset in range(start, total, args.batch_size):
        batch_products = products[offset : offset + args.batch_size]
        batch = encode_batch(
            args.backend,
            encoder,
            [semantic_text(product) for product in batch_products],
            args.dimension,
            args.batch_size,
        )
        if matrix is None:
            matrix = np.lib.format.open_memmap(
                building_path, mode="w+", dtype=np.float16, shape=(total, int(batch.shape[1]))
            )
        matrix[offset : offset + len(batch)] = batch
        completed = offset + len(batch)
        if completed == total or completed % args.checkpoint_every < len(batch):
            matrix.flush()
            atomic_json(progress_path, {**expected, "completed_rows": completed, "dimension": int(matrix.shape[1])})
            print(json.dumps({"completed_rows": completed, "total_rows": total}), flush=True)

    assert matrix is not None
    matrix.flush()
    dimension = int(matrix.shape[1])
    del matrix
    os.replace(building_path, output)
    metadata = {
        "backend": args.backend,
        "model": expected["model"],
        "dimension": dimension,
        "shape": [total, dimension],
        "dtype": "float16",
        "catalog_sha256": digest,
        "catalog_row_count": catalog_row_count,
        "indexed_row_count": total,
        "complete_catalog": total == catalog_row_count,
        "build_provider": selected_provider,
        "parent_asins": [str(product["parent_asin"]) for product in products],
    }
    atomic_json(metadata_path, metadata)
    progress_path.unlink(missing_ok=True)
    print(json.dumps({key: value for key, value in metadata.items() if key != "parent_asins"}, indent=2))


if __name__ == "__main__":
    main()
