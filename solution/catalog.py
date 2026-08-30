from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
MATERIALS = (
    "cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk",
    "rayon", "fabric", "linen", "denim", "suede", "fleece", "rubber",
)
COLORS = (
    "black", "white", "blue", "red", "pink", "green", "brown", "gray",
    "grey", "purple", "yellow", "orange", "beige", "navy", "gold", "silver",
)
USE_CASES = (
    "hiking", "running", "gym", "winter", "outdoor", "work", "wedding",
    "formal", "casual", "travel", "school", "college", "rain", "sports",
)


def flatten(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(flatten(item) for item in value)
    return str(value)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", flatten(value)).lower()
    text = re.sub(r"(?<=\d)[,](?=\d)", "", text)
    return " ".join(TOKEN_RE.findall(text))


def tokens(value: object) -> list[str]:
    return TOKEN_RE.findall(normalize_text(value))


def leaf_category(product: dict) -> str:
    values = product.get("categories") or []
    return str(values[-1]) if values else ""


def exact_attributes(product: dict) -> str:
    corpus = normalize_text(
        [product.get("store"), product.get("details"), product.get("features")]
    )
    values = [word for word in (*MATERIALS, *COLORS, *USE_CASES) if re.search(rf"\b{re.escape(word)}\b", corpus)]
    if product.get("price") not in (None, ""):
        values.append(f"price {product['price']} budget {product['price']}")
    return " ".join(values)


def semantic_text(product: dict) -> str:
    """Normalized product text used by the neural dense index."""
    fields = [
        flatten(product.get("title"))[:200],
        flatten(product.get("store"))[:50],
        flatten(product.get("categories"))[:120],
        exact_attributes(product)[:100],
        flatten(product.get("features"))[:250],
        flatten(product.get("description"))[:80],
    ]
    return normalize_text(fields)


@dataclass(frozen=True)
class ProductDocument:
    parent_asin: str
    title: str
    category: str
    brand: str
    attributes: str
    features: str
    description: str
    semantic: str
    raw: dict


def to_document(product: dict) -> ProductDocument:
    return ProductDocument(
        parent_asin=str(product["parent_asin"]),
        title=normalize_text(product.get("title")),
        category=normalize_text(product.get("categories")),
        brand=normalize_text(product.get("store")),
        attributes=exact_attributes(product),
        features=normalize_text(product.get("features")),
        description=normalize_text(product.get("description")),
        semantic=semantic_text(product),
        raw=product,
    )


def iter_catalog(path: str | Path) -> Iterable[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_documents(path: str | Path) -> list[ProductDocument]:
    return [to_document(product) for product in iter_catalog(path)]


def product_attribute_values(product: dict) -> dict[str, set[str]]:
    corpus = normalize_text([product.get("title"), product.get("features"), product.get("details")])
    price = product.get("price")
    budget: set[str] = set()
    if isinstance(price, (int, float)):
        bounds = (25, 50, 100, 200)
        budget = {next((f"under_{bound}" for bound in bounds if price <= bound), "over_200")}
    size_matches = set(re.findall(r"\b(?:size\s*)?(xxs|xs|s|m|l|xl|xxl|\d{1,2}(?:\.5)?)\b", corpus))
    return {
        "category": {normalize_text(leaf_category(product))} - {""},
        "material": {word for word in MATERIALS if re.search(rf"\b{word}\b", corpus)},
        "color": {word for word in COLORS if re.search(rf"\b{word}\b", corpus)},
        "size": size_matches,
        "style": {word for word in ("casual", "formal", "athletic", "classic", "slim", "relaxed") if word in corpus},
        "brand": {normalize_text(product.get("store"))} - {""},
        "budget": budget,
        "feature": {word for word in ("waterproof", "lightweight", "comfortable", "durable", "breathable", "warm", "stretch") if word in corpus},
        "use_case": {word for word in USE_CASES if re.search(rf"\b{word}\b", corpus)},
    }
