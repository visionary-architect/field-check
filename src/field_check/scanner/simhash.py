"""SimHash near-duplicate detection via configurable-width fingerprinting."""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# SimHash configuration
SIMHASH_BITS = 64
DEFAULT_THRESHOLD = 5  # Hamming distance for ~92% similarity
MIN_TEXT_LENGTH = 50  # Skip very short texts (noisy fingerprints)

# Tokenization pattern
_WORD_PATTERN = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    """Tokenize text into 3-shingles for SimHash computation.

    Args:
        text: Input text to tokenize.

    Returns:
        List of 3-shingle strings (or individual tokens if < 3 tokens).
    """
    words = _WORD_PATTERN.findall(text.lower())
    if len(words) < 3:
        return words
    return [f"{words[i]} {words[i + 1]} {words[i + 2]}" for i in range(len(words) - 2)]


def compute_simhash(text: str, bits: int = SIMHASH_BITS) -> int:
    """Compute a SimHash fingerprint from text.

    Uses MD5 hashing of 3-shingles with weighted bit accumulation.
    Supports 64-bit or 128-bit fingerprints.

    Args:
        text: Input text to fingerprint.
        bits: Fingerprint width (64 or 128).

    Returns:
        Integer fingerprint of the specified width.
    """
    shingles = _tokenize(text)
    if not shingles:
        return 0

    vector = [0] * bits
    # MD5 produces 128 bits; use 8 bytes for 64-bit, 16 for 128-bit
    hash_bytes = 8 if bits <= 64 else 16

    for shingle in shingles:
        digest = hashlib.md5(shingle.encode("utf-8")).digest()
        hash_val = int.from_bytes(digest[:hash_bytes], "big")

        for i in range(bits):
            if hash_val & (1 << i):
                vector[i] += 1
            else:
                vector[i] -= 1

    fingerprint = 0
    for i in range(bits):
        if vector[i] > 0:
            fingerprint |= 1 << i

    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Compute Hamming distance between two fingerprints.

    Args:
        a: First fingerprint.
        b: Second fingerprint.

    Returns:
        Number of differing bits.
    """
    return bin(a ^ b).count("1")


def similarity_score(a: int, b: int, bits: int = SIMHASH_BITS) -> float:
    """Compute similarity score between two fingerprints.

    Args:
        a: First fingerprint.
        b: Second fingerprint.
        bits: Fingerprint width for normalization.

    Returns:
        Similarity between 0.0 (completely different) and 1.0 (identical).
    """
    return 1.0 - hamming_distance(a, b) / bits


# ---------------------------------------------------------------------------
# Union-Find for transitive clustering
# ---------------------------------------------------------------------------


class _UnionFind:
    """Disjoint set with path compression for clustering."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry

    def groups(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for item in self.parent:
            result[self.find(item)].append(item)
        return dict(result)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NearDuplicateCluster:
    """A group of near-duplicate files."""

    paths: list[str] = field(default_factory=list)
    similarity: float = 0.0


@dataclass
class SimHashResult:
    """Aggregate results from near-duplicate detection."""

    total_analyzed: int = 0
    total_clusters: int = 0
    total_files_in_clusters: int = 0
    threshold: int = DEFAULT_THRESHOLD
    clusters: list[NearDuplicateCluster] = field(default_factory=list)
    fingerprints: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------


def _band_candidates(
    fingerprints: list[int], num_bands: int, bits: int = SIMHASH_BITS,
) -> set[tuple[int, int]]:
    """Find candidate pairs using band bucketing (locality-sensitive hashing).

    Divides each fingerprint into num_bands segments. Pairs sharing any
    identical segment are candidates for exact Hamming distance check.
    By pigeonhole, if Hamming distance ≤ num_bands-1, at least one
    segment must be identical — guaranteeing zero false negatives.
    """
    bits_per_band = bits // num_bands
    candidates: set[tuple[int, int]] = set()

    for band in range(num_bands):
        shift = band * bits_per_band
        # Last band gets remaining bits
        width = bits_per_band if band < num_bands - 1 else bits - shift
        mask = (1 << width) - 1

        buckets: dict[int, list[int]] = defaultdict(list)
        for idx, fp in enumerate(fingerprints):
            band_val = (fp >> shift) & mask
            buckets[band_val].append(idx)

        for indices in buckets.values():
            if len(indices) >= 2:
                for i in range(len(indices)):
                    for j in range(i + 1, len(indices)):
                        candidates.add((indices[i], indices[j]))

    return candidates


def _faiss_candidates(
    fingerprints: list[int], threshold: int, bits: int = SIMHASH_BITS,
) -> set[tuple[int, int]] | None:
    """Find candidate pairs using Faiss binary index (optional).

    Uses IndexBinaryFlat for exact Hamming distance search. Returns None
    if faiss is not available, falling back to band bucketing.
    """
    try:
        import faiss  # type: ignore[import-untyped]
        import numpy as np
    except ImportError:
        return None

    n = len(fingerprints)
    if n < 2:
        return set()

    # Convert fingerprints to byte arrays for Faiss binary index
    byte_width = bits // 8
    data = np.zeros((n, byte_width), dtype=np.uint8)
    for i, fp in enumerate(fingerprints):
        data[i] = np.frombuffer(
            fp.to_bytes(byte_width, byteorder="big"), dtype=np.uint8
        )

    index = faiss.IndexBinaryFlat(bits)
    index.add(data)

    # Range search: find all pairs within threshold Hamming distance
    # Use k-nearest neighbor search with k = min(n, 100) as proxy
    k = min(n, 100)
    distances, indices = index.search(data, k)

    candidates: set[tuple[int, int]] = set()
    for i in range(n):
        for j_pos in range(k):
            j = int(indices[i][j_pos])
            dist = int(distances[i][j_pos])
            if j != i and dist <= threshold:
                pair = (min(i, j), max(i, j))
                candidates.add(pair)

    return candidates


def detect_near_duplicates(
    text_cache: dict[str, str],
    threshold: int = DEFAULT_THRESHOLD,
    bits: int = SIMHASH_BITS,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SimHashResult:
    """Detect near-duplicate files using SimHash fingerprinting.

    Computes SimHash for each file, then performs pairwise comparison
    to find files within the Hamming distance threshold. Supports
    64-bit or 128-bit fingerprints. Uses union-find for transitive clustering.

    Args:
        text_cache: Dict of filepath -> extracted text content.
        threshold: Maximum Hamming distance to consider near-duplicate.
        bits: Fingerprint width (64 or 128). 128-bit reduces false positives.
        progress_callback: Called with (current, total) after each file.

    Returns:
        SimHashResult with clusters and statistics.
    """
    # Scale threshold proportionally for 128-bit
    if bits == 128 and threshold == DEFAULT_THRESHOLD:
        threshold = threshold * 2  # proportional scaling
    result = SimHashResult(threshold=threshold)

    # Step 1: Compute fingerprints (skip short texts)
    paths: list[str] = []
    fingerprints: list[int] = []

    total = len(text_cache)
    for i, (path, text) in enumerate(text_cache.items()):
        if len(text) >= MIN_TEXT_LENGTH:
            fp = compute_simhash(text, bits=bits)
            paths.append(path)
            fingerprints.append(fp)
            result.fingerprints[path] = fp

        if progress_callback is not None:
            progress_callback(i + 1, total)

    result.total_analyzed = len(paths)

    if result.total_analyzed < 2:
        return result

    # Step 2: Find candidate pairs (Faiss → band bucketing fallback)
    uf = _UnionFind()
    for i in range(len(paths)):
        uf.find(paths[i])  # ensure all paths are in the union-find

    candidates = _faiss_candidates(fingerprints, threshold, bits=bits)
    if candidates is None:
        # Fallback: band bucketing via pigeonhole principle
        num_bands = min(threshold + 1, bits)
        candidates = _band_candidates(fingerprints, num_bands, bits=bits)

    for i, j in candidates:
        dist = hamming_distance(fingerprints[i], fingerprints[j])
        if dist <= threshold:
            uf.union(paths[i], paths[j])

    # Step 3: Build clusters (only groups with 2+ members)
    groups = uf.groups()
    for members in groups.values():
        if len(members) < 2:
            continue

        # Calculate average pairwise similarity
        member_fps = [result.fingerprints[p] for p in members]
        total_sim = 0.0
        pair_count = 0
        for mi in range(len(member_fps)):
            for mj in range(mi + 1, len(member_fps)):
                total_sim += similarity_score(member_fps[mi], member_fps[mj], bits)
                pair_count += 1

        avg_sim = total_sim / pair_count if pair_count > 0 else 0.0

        result.clusters.append(
            NearDuplicateCluster(paths=sorted(members), similarity=avg_sim)
        )

    # Sort clusters: largest first, then by similarity descending
    result.clusters.sort(key=lambda c: (len(c.paths), c.similarity), reverse=True)

    result.total_clusters = len(result.clusters)
    result.total_files_in_clusters = sum(len(c.paths) for c in result.clusters)

    return result
