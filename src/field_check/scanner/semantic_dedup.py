"""Semantic near-duplicate detection via SemHash (optional).

Uses Model2Vec embeddings to find semantically similar documents
beyond what SimHash/MinHash can detect (catches paraphrases, translations).
Requires `semhash` package: pip install field-check[semantic]
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 50
DEFAULT_SIMILARITY_THRESHOLD = 0.85


@dataclass
class SemanticCluster:
    """A group of semantically similar files."""

    paths: list[str] = field(default_factory=list)
    similarity: float = 0.0


@dataclass
class SemanticDedupResult:
    """Aggregate results from semantic near-duplicate detection."""

    total_analyzed: int = 0
    total_clusters: int = 0
    total_files_in_clusters: int = 0
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    clusters: list[SemanticCluster] = field(default_factory=list)


def detect_semantic_duplicates(
    text_cache: dict[str, str],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SemanticDedupResult:
    """Detect semantically similar documents using SemHash.

    Uses Model2Vec embeddings to compute document similarity, catching
    paraphrases and near-translations that text-based methods miss.

    Args:
        text_cache: Dict of filepath -> extracted text content.
        threshold: Cosine similarity threshold (0.0-1.0).
        progress_callback: Called with (current, total) after each file.

    Returns:
        SemanticDedupResult with clusters. Empty if semhash not installed.
    """
    result = SemanticDedupResult(threshold=threshold)

    try:
        from semhash import SemHash  # type: ignore[import-untyped]
    except ImportError:
        logger.debug(
            "semhash not installed — skipping semantic dedup. "
            "Install with: pip install field-check[semantic]"
        )
        return result

    # Filter to texts long enough for meaningful embedding
    paths: list[str] = []
    texts: list[str] = []
    total = len(text_cache)

    for i, (path, text) in enumerate(text_cache.items()):
        if len(text) >= MIN_TEXT_LENGTH:
            paths.append(path)
            texts.append(text[:5000])  # Limit text length for embedding

        if progress_callback is not None:
            progress_callback(i + 1, total)

    result.total_analyzed = len(paths)

    if result.total_analyzed < 2:
        return result

    try:
        # Build SemHash index and find duplicates
        semhash = SemHash.from_records(texts)
        duplicates = semhash.self_find_duplicates(threshold=threshold)

        # Build clusters from duplicate groups
        # Track which indices have been clustered
        clustered: set[int] = set()
        for dup_record in duplicates:
            # Find the index of the original text
            try:
                orig_idx = texts.index(dup_record.text)
            except ValueError:
                continue

            if orig_idx in clustered:
                continue

            cluster_paths = [paths[orig_idx]]
            clustered.add(orig_idx)

            for dup in dup_record.duplicates:
                try:
                    dup_idx = texts.index(dup.text)
                except ValueError:
                    continue
                if dup_idx not in clustered:
                    cluster_paths.append(paths[dup_idx])
                    clustered.add(dup_idx)

            if len(cluster_paths) >= 2:
                result.clusters.append(
                    SemanticCluster(
                        paths=sorted(cluster_paths),
                        similarity=threshold,
                    )
                )
    except Exception:
        logger.warning("Semantic dedup failed", exc_info=True)
        return result

    result.clusters.sort(key=lambda c: len(c.paths), reverse=True)
    result.total_clusters = len(result.clusters)
    result.total_files_in_clusters = sum(len(c.paths) for c in result.clusters)

    return result
