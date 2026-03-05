"""Tests for SimHash near-duplicate detection."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig, load_config
from field_check.scanner.simhash import (
    DEFAULT_THRESHOLD,
    MIN_TEXT_LENGTH,
    SIMHASH_BITS,
    compute_simhash,
    detect_near_duplicates,
    hamming_distance,
    similarity_score,
)

# ---------------------------------------------------------------------------
# SimHash computation tests
# ---------------------------------------------------------------------------


class TestComputeSimHash:
    """Test core SimHash fingerprinting."""

    def test_deterministic(self) -> None:
        text = "The quick brown fox jumps over the lazy dog in the park."
        assert compute_simhash(text) == compute_simhash(text)

    def test_different_texts(self) -> None:
        h1 = compute_simhash(
            "The quarterly report shows strong growth in the technology sector."
        )
        h2 = compute_simhash(
            "Machine learning algorithms have revolutionized natural language processing."
        )
        assert h1 != h2

    def test_similar_texts_close_distance(self) -> None:
        base = (
            "The quarterly financial report for the fiscal year demonstrates "
            "remarkable growth across all business segments. Revenue increased "
            "by fifteen percent compared to the previous quarter driven by "
            "expansion in the technology sector. The company launched three "
            "new product lines targeting distinct market segments."
        )
        variant = base.replace("fifteen", "fourteen")
        dist = hamming_distance(compute_simhash(base), compute_simhash(variant))
        # Similar texts should have distance much less than 32 (random would be ~32)
        assert dist < 20

    def test_empty_text(self) -> None:
        assert compute_simhash("") == 0

    def test_short_text(self) -> None:
        h = compute_simhash("hello world")
        assert isinstance(h, int)
        assert 0 <= h < 2**SIMHASH_BITS

    def test_long_text(self) -> None:
        text = "This is a test sentence for SimHash computation. " * 100
        h = compute_simhash(text)
        assert isinstance(h, int)
        assert 0 <= h < 2**SIMHASH_BITS


# ---------------------------------------------------------------------------
# Hamming distance tests
# ---------------------------------------------------------------------------


class TestHammingDistance:
    """Test Hamming distance computation."""

    def test_identical(self) -> None:
        assert hamming_distance(0, 0) == 0
        assert hamming_distance(12345, 12345) == 0

    def test_completely_different(self) -> None:
        # All 64 bits flipped
        mask = (1 << SIMHASH_BITS) - 1
        assert hamming_distance(0, mask) == SIMHASH_BITS

    def test_known_values(self) -> None:
        # 0b0001 vs 0b0010 = 2 bits different
        assert hamming_distance(0b0001, 0b0010) == 2
        # 0b1111 vs 0b0000 = 4 bits different
        assert hamming_distance(0b1111, 0b0000) == 4
        # 0b1010 vs 0b1011 = 1 bit different
        assert hamming_distance(0b1010, 0b1011) == 1


# ---------------------------------------------------------------------------
# Similarity score tests
# ---------------------------------------------------------------------------


class TestSimilarityScore:
    """Test similarity score computation."""

    def test_identical(self) -> None:
        assert similarity_score(42, 42) == 1.0

    def test_range(self) -> None:
        score = similarity_score(0, (1 << SIMHASH_BITS) - 1)
        assert 0.0 <= score <= 1.0
        assert score == 0.0  # All bits different


# ---------------------------------------------------------------------------
# Near-duplicate detection tests
# ---------------------------------------------------------------------------


class TestDetectNearDuplicates:
    """Test end-to-end near-duplicate detection."""

    def test_empty_cache(self) -> None:
        result = detect_near_duplicates({})
        assert result.total_analyzed == 0
        assert result.total_clusters == 0

    def test_no_duplicates(self) -> None:
        cache = {
            "a.txt": (
                "The quarterly financial report shows strong growth "
                "in the technology sector with significant revenue."
            ),
            "b.txt": (
                "Machine learning algorithms have revolutionized "
                "natural language processing and computer vision."
            ),
        }
        result = detect_near_duplicates(cache, threshold=3)
        assert result.total_clusters == 0

    def test_near_duplicate_pair(self) -> None:
        base = (
            "The quarterly financial report for the fiscal year demonstrates "
            "remarkable growth across all business segments. Revenue increased "
            "by fifteen percent compared to the previous quarter driven by "
            "expansion in the technology sector. The company launched three "
            "new product lines targeting distinct market segments."
        )
        cache = {
            "orig.txt": base,
            "copy.txt": base,  # Exact copy → distance 0
            "diff.txt": (
                "Machine learning algorithms have transformed the field "
                "of natural language processing with new architectures "
                "and training methods that push boundaries further."
            ),
        }
        result = detect_near_duplicates(cache, threshold=5)
        assert result.total_clusters >= 1
        # The exact copies should be in a cluster
        cluster_paths = result.clusters[0].paths
        assert "orig.txt" in cluster_paths
        assert "copy.txt" in cluster_paths
        assert "diff.txt" not in cluster_paths

    def test_transitive_clustering(self) -> None:
        # A identical to B, B identical to C → all in one cluster
        text = (
            "The annual business review indicates positive outcomes "
            "across all divisions. Market share has grown steadily "
            "and customer retention rates remain at historical highs."
        )
        cache = {
            "a.txt": text,
            "b.txt": text,
            "c.txt": text,
        }
        result = detect_near_duplicates(cache, threshold=5)
        assert result.total_clusters == 1
        assert len(result.clusters[0].paths) == 3

    def test_short_text_skipped(self) -> None:
        cache = {
            "short.txt": "Hello",  # < MIN_TEXT_LENGTH
            "also_short.txt": "Hello",
            "long_enough.txt": "x " * MIN_TEXT_LENGTH,
        }
        result = detect_near_duplicates(cache)
        # Short texts should be excluded from analysis
        assert result.total_analyzed == 1  # only long_enough.txt

    def test_progress_callback(self) -> None:
        calls: list[tuple[int, int]] = []
        cache = {
            "a.txt": "Text content that is long enough for analysis. " * 5,
            "b.txt": "Different text content for comparison purposes. " * 5,
        }
        detect_near_duplicates(
            cache, progress_callback=lambda c, t: calls.append((c, t))
        )
        assert len(calls) == 2
        assert calls[-1] == (2, 2)

    def test_threshold_zero(self) -> None:
        # Threshold 0 = only exact fingerprint matches
        base = (
            "The quarterly report demonstrates growth across segments "
            "with revenue increasing by fifteen percent this quarter."
        )
        cache = {
            "a.txt": base,
            "b.txt": base,  # Exact same → distance 0
            "c.txt": base.replace("fifteen", "fourteen"),  # Slightly different
        }
        result = detect_near_duplicates(cache, threshold=0)
        # Only exact fingerprint matches
        assert result.total_clusters == 1
        assert len(result.clusters[0].paths) == 2

    def test_with_neardup_fixture(self, tmp_neardup_corpus: Path) -> None:
        # Read files from fixture
        cache = {}
        for f in tmp_neardup_corpus.iterdir():
            if f.is_file():
                cache[str(f)] = f.read_text(encoding="utf-8")

        # With generous threshold, near-duplicates should cluster
        result = detect_near_duplicates(cache, threshold=10)
        # At least the 3 report variants should form a cluster
        assert result.total_analyzed == 5
        report_paths = {str(tmp_neardup_corpus / f"report_v{i}.txt") for i in range(1, 4)}
        found_cluster = False
        for cluster in result.clusters:
            cluster_set = set(cluster.paths)
            if report_paths.issubset(cluster_set):
                found_cluster = True
                break
        assert found_cluster, "Report variants should form a near-duplicate cluster"


# ---------------------------------------------------------------------------
# Config threshold tests
# ---------------------------------------------------------------------------


class TestConfigThreshold:
    """Test simhash_threshold in config."""

    def test_default_threshold(self) -> None:
        config = FieldCheckConfig()
        assert config.simhash_threshold == DEFAULT_THRESHOLD

    def test_yaml_threshold(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".field-check.yaml"
        config_file.write_text(
            "simhash:\n  threshold: 8\n", encoding="utf-8"
        )
        config = load_config(tmp_path)
        assert config.simhash_threshold == 8

    def test_yaml_threshold_clamped(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".field-check.yaml"
        config_file.write_text(
            "simhash:\n  threshold: 100\n", encoding="utf-8"
        )
        config = load_config(tmp_path)
        assert config.simhash_threshold == 64  # Clamped to max
