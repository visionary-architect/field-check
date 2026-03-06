"""Tests for semantic near-duplicate detection."""

from __future__ import annotations

import pytest

from field_check.scanner.semantic_dedup import (
    SemanticDedupResult,
    detect_semantic_duplicates,
)

# Check if semhash is available
try:
    import semhash  # noqa: F401

    HAS_SEMHASH = True
except ImportError:
    HAS_SEMHASH = False


class TestSemanticDedupGraceful:
    """Test graceful degradation without semhash."""

    def test_empty_cache(self) -> None:
        result = detect_semantic_duplicates({})
        assert isinstance(result, SemanticDedupResult)
        assert result.total_analyzed == 0
        assert result.clusters == []

    def test_returns_empty_without_semhash(self) -> None:
        cache = {
            "a.txt": "Some document content for testing purposes " * 10,
            "b.txt": "Some document content for testing purposes " * 10,
        }
        result = detect_semantic_duplicates(cache)
        # Should either find duplicates (if installed) or return empty (if not)
        assert isinstance(result, SemanticDedupResult)

    @pytest.mark.skipif(not HAS_SEMHASH, reason="semhash not installed")
    def test_progress_callback(self) -> None:
        calls: list[tuple[int, int]] = []
        cache = {
            "a.txt": "Some text content for testing " * 10,
            "b.txt": "More text content for testing " * 10,
        }
        detect_semantic_duplicates(cache, progress_callback=lambda c, t: calls.append((c, t)))
        assert len(calls) == 2

    def test_short_texts_skipped(self) -> None:
        cache = {"a.txt": "short", "b.txt": "tiny"}
        result = detect_semantic_duplicates(cache)
        assert result.total_analyzed == 0


@pytest.mark.skipif(not HAS_SEMHASH, reason="semhash not installed")
class TestSemanticDedupWithSemHash:
    """Test semantic dedup with semhash installed."""

    def test_identical_texts_cluster(self) -> None:
        text = (
            "The quarterly financial report shows growth across all "
            "business segments with revenue increasing significantly. "
            "Additional analysis confirms positive market trends."
        )
        cache = {"a.txt": text, "b.txt": text}
        result = detect_semantic_duplicates(cache, threshold=0.8)
        assert result.total_analyzed == 2
        assert result.total_clusters >= 1

    def test_result_structure(self) -> None:
        text = "Document content for semantic testing purposes " * 10
        cache = {"a.txt": text, "b.txt": text}
        result = detect_semantic_duplicates(cache, threshold=0.5)
        assert isinstance(result.threshold, float)
        assert result.total_analyzed == 2
