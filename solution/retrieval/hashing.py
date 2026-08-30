from __future__ import annotations

import math
import zlib
from collections import Counter

from solution.catalog import tokens


def hashing_vector(text: str, dimension: int = 384):
    """Signed feature-hashing vector with unigram and adjacent-bigram features."""
    import numpy as np

    words = tokens(text)
    features = words + [f"{left}_{right}" for left, right in zip(words, words[1:])]
    counts = Counter(features)
    vector = np.zeros(dimension, dtype=np.float32)
    for feature, count in counts.items():
        digest = zlib.crc32(feature.encode("utf-8"))
        index = digest % dimension
        sign = -1.0 if digest & 0x80000000 else 1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector

