"""SimHash near-duplicate detection via 64-bit fingerprinting."""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

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


def compute_simhash(text: str) -> int:
    """Compute a 64-bit SimHash fingerprint from text.

    Uses MD5 hashing of 3-shingles with weighted bit accumulation.

    Args:
        text: Input text to fingerprint.

    Returns:
        64-bit integer fingerprint.
    """
    shingles = _tokenize(text)
    if not shingles:
        return 0

    vector = [0] * SIMHASH_BITS

    for shingle in shingles:
        digest = hashlib.md5(shingle.encode("utf-8")).digest()
        hash_val = int.from_bytes(digest[:8], "big")

        for i in range(SIMHASH_BITS):
            if hash_val & (1 << i):
                vector[i] += 1
            else:
                vector[i] -= 1

    fingerprint = 0
    for i in range(SIMHASH_BITS):
        if vector[i] > 0:
            fingerprint |= 1 << i

    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Compute Hamming distance between two fingerprints.

    Args:
        a: First 64-bit fingerprint.
        b: Second 64-bit fingerprint.

    Returns:
        Number of differing bits (0 to 64).
    """
    return bin(a ^ b).count("1")


def similarity_score(a: int, b: int) -> float:
    """Compute similarity score between two fingerprints.

    Args:
        a: First 64-bit fingerprint.
        b: Second 64-bit fingerprint.

    Returns:
        Similarity between 0.0 (completely different) and 1.0 (identical).
    """
    return 1.0 - hamming_distance(a, b) / SIMHASH_BITS


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


def detect_near_duplicates(
    text_cache: dict[str, str],
    threshold: int = DEFAULT_THRESHOLD,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SimHashResult:
    """Detect near-duplicate files using SimHash fingerprinting.

    Computes 64-bit SimHash for each file, then performs pairwise
    comparison to find files within the Hamming distance threshold.
    Uses union-find for transitive clustering.

    Args:
        text_cache: Dict of filepath -> extracted text content.
        threshold: Maximum Hamming distance to consider near-duplicate (0-64).
        progress_callback: Called with (current, total) after each file.

    Returns:
        SimHashResult with clusters and statistics.
    """
    result = SimHashResult(threshold=threshold)

    # Step 1: Compute fingerprints (skip short texts)
    paths: list[str] = []
    fingerprints: list[int] = []

    total = len(text_cache)
    for i, (path, text) in enumerate(text_cache.items()):
        if len(text) >= MIN_TEXT_LENGTH:
            fp = compute_simhash(text)
            paths.append(path)
            fingerprints.append(fp)
            result.fingerprints[path] = fp

        if progress_callback is not None:
            progress_callback(i + 1, total)

    result.total_analyzed = len(paths)

    if result.total_analyzed < 2:
        return result

    # Step 2: Pairwise comparison + union-find clustering
    uf = _UnionFind()
    for i in range(len(paths)):
        uf.find(paths[i])  # ensure all paths are in the union-find

    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
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
                total_sim += similarity_score(member_fps[mi], member_fps[mj])
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
