from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solution.catalog import COLORS, MATERIALS, iter_catalog, normalize_text


FIELDS = ("title", "features", "description", "price", "categories", "details", "average_rating", "rating_number", "store")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile the immutable product catalog")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--json-output", default="artifacts/catalog_profile.json")
    parser.add_argument("--markdown-output", default="experiments/CATALOG_EDA.md")
    args = parser.parse_args()
    products = list(iter_catalog(args.catalog))
    ids = [str(product["parent_asin"]) for product in products]
    coverage = {field: sum(product.get(field) not in (None, "", [], {}) for product in products) for field in FIELDS}
    prices = [float(product["price"]) for product in products if isinstance(product.get("price"), (int, float))]
    duplicate_titles = Counter(normalize_text(product.get("title")) for product in products)
    corpus = [normalize_text([product.get("title"), product.get("features"), product.get("details")]) for product in products]
    profile = {
        "catalog": args.catalog,
        "row_count": len(products),
        "unique_parent_asin_count": len(set(ids)),
        "duplicate_parent_asin_count": len(ids) - len(set(ids)),
        "duplicate_normalized_title_groups": sum(count > 1 for title, count in duplicate_titles.items() if title),
        "field_coverage": {field: {"count": coverage[field], "ratio": round(coverage[field] / len(products), 6)} for field in FIELDS},
        "price": {
            "numeric_count": len(prices),
            "min": min(prices) if prices else None,
            "median": statistics.median(prices) if prices else None,
            "max": max(prices) if prices else None,
        },
        "attribute_coverage": {
            "material": round(sum(any(word in text for word in MATERIALS) for text in corpus) / len(products), 6),
            "color": round(sum(any(word in text for word in COLORS) for text in corpus) / len(products), 6),
        },
    }
    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Catalog EDA", "", f"- Rows: {profile['row_count']:,}",
        f"- Unique parent_asin: {profile['unique_parent_asin_count']:,}",
        f"- Duplicate parent_asin: {profile['duplicate_parent_asin_count']:,}",
        f"- Duplicate normalized-title groups: {profile['duplicate_normalized_title_groups']:,}", "",
        "## Field coverage", "", "| Field | Count | Coverage |", "|---|---:|---:|",
    ]
    lines.extend(f"| {field} | {value['count']:,} | {value['ratio']:.1%} |" for field, value in profile["field_coverage"].items())
    lines.extend(["", "## Attribute signals", "", f"- Material keyword coverage: {profile['attribute_coverage']['material']:.1%}", f"- Color keyword coverage: {profile['attribute_coverage']['color']:.1%}"])
    md_path = Path(args.markdown_output)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(profile, indent=2))


if __name__ == "__main__":
    main()
