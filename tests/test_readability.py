"""Tests for readability scoring module."""

from __future__ import annotations

from unittest.mock import patch

from field_check.scanner.readability import (
    LOW_QUALITY_THRESHOLD,
    ReadabilityResult,
    ReadabilityScore,
    analyze_readability,
)


class TestReadability:
    """Tests for readability analysis."""

    def test_empty_cache(self) -> None:
        """Empty text cache returns empty result."""
        result = analyze_readability({})
        assert result.total_checked == 0
        assert result.low_quality_count == 0
        assert result.scores == []

    def test_short_text_skipped(self) -> None:
        """Text shorter than minimum length is skipped."""
        cache = {"short.txt": "Hello world"}
        result = analyze_readability(cache)
        assert result.total_checked == 0

    def test_readable_text(self) -> None:
        """Clear, simple text scores above low-quality threshold."""
        # Simple sentences that should score well on Flesch Reading Ease
        text = (
            "The cat sat on the mat. The dog ran in the park. "
            "Birds fly in the sky. Fish swim in the sea. "
            "The sun is bright today. Children play outside. "
        ) * 5  # Repeat to exceed minimum length
        cache = {"simple.txt": text}
        result = analyze_readability(cache)
        assert result.total_checked == 1
        assert len(result.scores) == 1
        assert result.scores[0].flesch_reading_ease > LOW_QUALITY_THRESHOLD
        assert not result.scores[0].is_low_quality

    def test_low_quality_detection(self) -> None:
        """Gibberish/dense text scores below threshold."""
        # Simulate OCR garbage — random technical jargon with no structure
        text = (
            "xJk7 Qr9z mNp4 tLw2 vBx8 hYd3 fRs5 kWm1 zPq6 cNj9 gTv4 bXh7 yLr2 dKs8 wMf3 jQp5 "
        ) * 20
        cache = {"garbage.txt": text}
        result = analyze_readability(cache)
        assert result.total_checked == 1
        if result.scores:
            assert result.scores[0].flesch_reading_ease < LOW_QUALITY_THRESHOLD
            assert result.scores[0].is_low_quality
            assert result.low_quality_count == 1

    def test_multiple_files(self) -> None:
        """Multiple files are all scored."""
        simple = "The cat sat on the mat. " * 20
        cache = {
            "a.txt": simple,
            "b.txt": simple,
            "c.txt": simple,
        }
        result = analyze_readability(cache)
        assert result.total_checked == 3
        assert len(result.scores) == 3
        assert result.avg_flesch_score > 0

    def test_graceful_without_textstat(self) -> None:
        """Returns empty result when textstat is not installed."""
        with patch.dict("sys.modules", {"textstat": None}):
            import importlib

            from field_check.scanner import readability

            importlib.reload(readability)
            result = readability.analyze_readability({"test.txt": "x" * 300})
            assert result.total_checked == 0
            assert result.scores == []
            # Restore module
            importlib.reload(readability)

    def test_score_rounding(self) -> None:
        """Scores are rounded to 1 decimal place."""
        text = "The cat sat on the mat. " * 20
        result = analyze_readability({"test.txt": text})
        if result.scores:
            score_str = str(result.scores[0].flesch_reading_ease)
            # Should have at most 1 decimal place
            if "." in score_str:
                assert len(score_str.split(".")[1]) <= 1

    def test_avg_score_calculated(self) -> None:
        """Average Flesch score is computed across all files."""
        text = "The cat sat on the mat. " * 20
        cache = {"a.txt": text, "b.txt": text}
        result = analyze_readability(cache)
        assert result.avg_flesch_score > 0
        # Average of same text should equal individual score
        if result.scores:
            individual = result.scores[0].flesch_reading_ease
            assert abs(result.avg_flesch_score - individual) < 1.0


class TestReadabilityDataclasses:
    """Tests for readability dataclass structure."""

    def test_readability_score_fields(self) -> None:
        """ReadabilityScore has expected fields."""
        s = ReadabilityScore(path="test.pdf", flesch_reading_ease=65.2, is_low_quality=False)
        assert s.path == "test.pdf"
        assert s.flesch_reading_ease == 65.2
        assert not s.is_low_quality

    def test_readability_result_defaults(self) -> None:
        """ReadabilityResult has sensible defaults."""
        r = ReadabilityResult()
        assert r.total_checked == 0
        assert r.low_quality_count == 0
        assert r.avg_flesch_score == 0.0
        assert r.scores == []
