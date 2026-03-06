"""Tests for MinHash+LSH near-duplicate detection."""

from __future__ import annotations

import pytest

from field_check.scanner.minhash import (
    MinHashResult,
    _tokenize_shingles,
    detect_near_duplicates_minhash,
)

# Check if datasketch is available
try:
    import datasketch  # noqa: F401

    HAS_DATASKETCH = True
except ImportError:
    HAS_DATASKETCH = False


class TestTokenizeShingles:
    """Test shingle tokenization."""

    def test_basic_shingles(self) -> None:
        text = "the quick brown fox jumps"
        shingles = _tokenize_shingles(text, k=3)
        assert "the quick brown" in shingles
        assert "quick brown fox" in shingles
        assert "brown fox jumps" in shingles

    def test_short_text(self) -> None:
        shingles = _tokenize_shingles("hello world", k=3)
        assert shingles == {"hello", "world"}

    def test_empty_text(self) -> None:
        assert _tokenize_shingles("") == set()


class TestMinHashGracefulDegradation:
    """Test graceful degradation without datasketch."""

    def test_empty_cache(self) -> None:
        result = detect_near_duplicates_minhash({})
        assert isinstance(result, MinHashResult)
        assert result.total_analyzed == 0
        assert result.clusters == []


@pytest.mark.skipif(not HAS_DATASKETCH, reason="datasketch not installed")
class TestMinHashDetection:
    """Test MinHash near-duplicate detection (requires datasketch)."""

    def test_identical_texts_cluster(self) -> None:
        base = (
            "The quarterly report demonstrates growth across segments "
            "with revenue increasing by fifteen percent this quarter. "
            "Additional analysis reveals market trends and projections."
        )
        cache = {
            "a.txt": base,
            "b.txt": base,
            "c.txt": "Completely unrelated text about cooking pasta recipes " * 5,
        }
        result = detect_near_duplicates_minhash(cache, threshold=0.5)
        assert result.total_analyzed >= 2
        found = any(
            "a.txt" in c.paths and "b.txt" in c.paths
            for c in result.clusters
        )
        assert found

    def test_no_duplicates(self) -> None:
        cache = {
            "a.txt": "The quick brown fox jumps over the lazy dog " * 10,
            "b.txt": "Python programming language tutorials and examples " * 10,
            "c.txt": "Cooking recipes for Italian pasta dishes and sauces " * 10,
        }
        result = detect_near_duplicates_minhash(cache, threshold=0.9)
        assert result.total_clusters == 0

    def test_progress_callback(self) -> None:
        calls: list[tuple[int, int]] = []
        cache = {
            "a.txt": "Some text content for testing " * 10,
            "b.txt": "More text content for testing " * 10,
        }
        detect_near_duplicates_minhash(
            cache, progress_callback=lambda c, t: calls.append((c, t))
        )
        assert len(calls) == 2

    def test_short_texts_skipped(self) -> None:
        cache = {"a.txt": "short", "b.txt": "tiny"}
        result = detect_near_duplicates_minhash(cache)
        assert result.total_analyzed == 0

    def test_result_structure(self) -> None:
        base = "Document content for near-duplicate testing purposes " * 10
        cache = {"a.txt": base, "b.txt": base}
        result = detect_near_duplicates_minhash(cache, threshold=0.5)
        assert isinstance(result.threshold, float)
        assert result.total_analyzed == 2
