"""Tests for mojibake (encoding damage) detection."""

from __future__ import annotations

from field_check.scanner.mojibake import MojibakeResult, detect_mojibake


def test_clean_text_no_mojibake() -> None:
    """Clean text should not be flagged."""
    cache = {
        "file1.txt": "This is perfectly normal English text with no encoding issues.",
        "file2.txt": "Another clean document with standard ASCII characters only.",
    }
    result = detect_mojibake(cache)
    assert result.total_checked == 2
    assert result.files_with_mojibake == 0
    assert result.mojibake_files == []


def test_mojibake_detected() -> None:
    """Text with encoding damage should be flagged."""
    # Simulate UTF-8 text decoded as latin-1 (classic mojibake)
    original = "Ça fait plaisir de résumer les résultats"
    damaged = original.encode("utf-8").decode("latin-1")
    cache = {"damaged.txt": damaged}
    result = detect_mojibake(cache)
    assert result.total_checked == 1
    assert result.files_with_mojibake == 1
    assert "damaged.txt" in result.mojibake_files


def test_short_text_skipped() -> None:
    """Text shorter than minimum length should be skipped."""
    cache = {"short.txt": "tiny"}
    result = detect_mojibake(cache)
    assert result.total_checked == 0
    assert result.files_with_mojibake == 0


def test_empty_cache() -> None:
    """Empty text cache should return zeroed result."""
    result = detect_mojibake({})
    assert result.total_checked == 0
    assert result.files_with_mojibake == 0
    assert result.mojibake_files == []


def test_mixed_clean_and_damaged() -> None:
    """Mix of clean and damaged files should only flag damaged ones."""
    clean = "This is a perfectly normal paragraph of English text."
    damaged = "RÃ©sumÃ© of qualificÃ©"  # common UTF-8→latin-1 mojibake
    # Pad damaged to meet minimum length
    damaged_padded = damaged + " " * 30

    cache = {
        "clean.txt": clean,
        "damaged.txt": damaged_padded,
    }
    result = detect_mojibake(cache)
    assert result.total_checked == 2
    assert result.files_with_mojibake >= 1
    assert "damaged.txt" in result.mojibake_files
    assert "clean.txt" not in result.mojibake_files


def test_result_dataclass_defaults() -> None:
    """MojibakeResult should have sensible defaults."""
    result = MojibakeResult()
    assert result.total_checked == 0
    assert result.files_with_mojibake == 0
    assert result.mojibake_files == []
