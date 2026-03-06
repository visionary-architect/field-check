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
        # NOTE: SemHash downloads a Model2Vec model from Hugging Face Hub
        # on first use. This is an intentional network call by the optional
        # semhash dependency; the user opts in by installing field-check[semantic].
        logger.info("Running semantic dedup (semhash may download a model on first use)")
        semhash_index = SemHash.from_records(texts)
        dedup_result = semhash_index.self_deduplicate(threshold=threshold)

        # Build a text→index map for O(1) lookup (handles duplicate texts)
        text_to_indices: dict[str, list[int]] = {}
        for idx, t in enumerate(texts):
            text_to_indices.setdefault(t, []).append(idx)

        # Build clusters from deduplicated groups
        clustered: set[int] = set()
        for item in dedup_result.selected_with_duplicates:
            record_text = item.record
            dup_texts_and_scores = item.duplicates  # list of (text, score)

            if not dup_texts_and_scores:
                continue

            # Find the index of the original record
            orig_indices = text_to_indices.get(record_text, [])
            orig_idx = next((i for i in orig_indices if i not in clustered), None)
            if orig_idx is None:
                continue

            cluster_paths = [paths[orig_idx]]
            clustered.add(orig_idx)

            for dup_text, _score in dup_texts_and_scores:
                dup_indices = text_to_indices.get(dup_text, [])
                dup_idx = next((i for i in dup_indices if i not in clustered), None)
                if dup_idx is not None:
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
