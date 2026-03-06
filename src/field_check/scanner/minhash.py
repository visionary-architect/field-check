"""MinHash+LSH near-duplicate detection via datasketch (optional).

Provides an alternative to SimHash using MinHash with Locality-Sensitive
Hashing for Jaccard similarity estimation. Requires `datasketch` package.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 50
_WORD_PATTERN = re.compile(r"\w+")

# Default Jaccard similarity threshold for near-duplicate detection
DEFAULT_JACCARD_THRESHOLD = 0.7


@dataclass
class MinHashCluster:
    """A group of near-duplicate files found via MinHash."""

    paths: list[str] = field(default_factory=list)
    similarity: float = 0.0


@dataclass
class MinHashResult:
    """Aggregate results from MinHash near-duplicate detection."""

    total_analyzed: int = 0
    total_clusters: int = 0
    total_files_in_clusters: int = 0
    threshold: float = DEFAULT_JACCARD_THRESHOLD
    clusters: list[MinHashCluster] = field(default_factory=list)


def _tokenize_shingles(text: str, k: int = 3) -> set[str]:
    """Tokenize text into k-shingles (word n-grams).

    Args:
        text: Input text.
        k: Shingle size (number of words).

    Returns:
        Set of k-shingle strings.
    """
    words = _WORD_PATTERN.findall(text.lower())
    if len(words) < k:
        return set(words)
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def detect_near_duplicates_minhash(
    text_cache: dict[str, str],
    threshold: float = DEFAULT_JACCARD_THRESHOLD,
    num_perm: int = 128,
    progress_callback: Callable[[int, int], None] | None = None,
) -> MinHashResult:
    """Detect near-duplicate files using MinHash+LSH.

    Uses datasketch's MinHash and MinHashLSH for efficient Jaccard
    similarity estimation. Gracefully returns empty result if datasketch
    is not installed.

    Args:
        text_cache: Dict of filepath -> extracted text content.
        threshold: Jaccard similarity threshold (0.0-1.0).
        num_perm: Number of permutation functions for MinHash.
        progress_callback: Called with (current, total) after each file.

    Returns:
        MinHashResult with clusters and statistics.
    """
    result = MinHashResult(threshold=threshold)

    try:
        from datasketch import MinHash, MinHashLSH  # type: ignore[import-untyped]
    except ImportError:
        logger.debug(
            "datasketch not installed — skipping MinHash detection. "
            "Install with: pip install field-check[dedup-extra]"
        )
        return result

    # Step 1: Compute MinHash signatures
    paths: list[str] = []
    signatures: list[MinHash] = []
    total = len(text_cache)

    for i, (path, text) in enumerate(text_cache.items()):
        if len(text) >= MIN_TEXT_LENGTH:
            shingles = _tokenize_shingles(text)
            if shingles:
                mh = MinHash(num_perm=num_perm)
                for s in shingles:
                    mh.update(s.encode("utf-8"))
                paths.append(path)
                signatures.append(mh)

        if progress_callback is not None:
            progress_callback(i + 1, total)

    result.total_analyzed = len(paths)

    if result.total_analyzed < 2:
        return result

    # Step 2: Build LSH index and query for candidates
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    for idx, (path, sig) in enumerate(zip(paths, signatures)):
        try:
            lsh.insert(str(idx), sig)
        except ValueError:
            # Duplicate key — skip
            pass

    # Step 3: Find connected components via union-find
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for idx in range(len(paths)):
        find(idx)
        candidates = lsh.query(signatures[idx])
        for cand_str in candidates:
            cand_idx = int(cand_str)
            if cand_idx != idx:
                union(idx, cand_idx)

    # Step 4: Build clusters
    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(paths)):
        groups[find(idx)].append(idx)

    for members in groups.values():
        if len(members) < 2:
            continue

        # Estimate average pairwise Jaccard similarity
        member_sigs = [signatures[i] for i in members]
        total_sim = 0.0
        pair_count = 0
        for mi in range(len(member_sigs)):
            for mj in range(mi + 1, len(member_sigs)):
                total_sim += member_sigs[mi].jaccard(member_sigs[mj])
                pair_count += 1

        avg_sim = total_sim / pair_count if pair_count > 0 else 0.0
        result.clusters.append(
            MinHashCluster(
                paths=sorted(paths[i] for i in members),
                similarity=avg_sim,
            )
        )

    result.clusters.sort(key=lambda c: (len(c.paths), c.similarity), reverse=True)
    result.total_clusters = len(result.clusters)
    result.total_files_in_clusters = sum(len(c.paths) for c in result.clusters)

    return result
