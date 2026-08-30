from __future__ import annotations

import argparse
import hashlib
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build normalized BGE product embeddings")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--backend", choices=("hashing", "fastembed"), default="hashing")
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--dimension", type=int, default=384)
    parser.add_argument("--output", default="artifacts/product_embeddings.npy")
    parser.add_argument("--metadata", default="artifacts/product_embeddings.meta.json")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, help="Optional smoke-test row limit; omit for the full catalog")
    args = parser.parse_args()
    catalog_path = Path(args.catalog)
    products = list(iter_catalog(catalog_path))
    if args.limit:
        products = products[:args.limit]
    texts = [semantic_text(product) for product in products]
    if args.backend == "fastembed":
        from fastembed import TextEmbedding

        encoder = TextEmbedding(model_name=args.model, providers=["CPUExecutionProvider"])
        matrix = np.asarray(list(encoder.passage_embed(texts, batch_size=args.batch_size)), dtype=np.float16)
    else:
        matrix = np.asarray([hashing_vector(text, args.dimension) for text in texts], dtype=np.float16)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, matrix)
    metadata = {
        "backend": args.backend,
        "model": args.model if args.backend == "fastembed" else "signed-hashing-unigram-bigram-v1",
        "dimension": int(matrix.shape[1]),
        "shape": list(matrix.shape),
        "dtype": str(matrix.dtype),
        "catalog_sha256": sha256(catalog_path),
        "catalog_row_count": len(products),
        "parent_asins": [str(product["parent_asin"]) for product in products],
    }
    Path(args.metadata).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in metadata.items() if key != "parent_asins"}, indent=2))


if __name__ == "__main__":
    main()
