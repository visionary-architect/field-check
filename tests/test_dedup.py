"""Tests for the BLAKE3 dedup scanner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from field_check.config import FieldCheckConfig
from field_check.scanner import WalkResult, walk_directory
from field_check.scanner.dedup import compute_hashes


def _walk(path: Path) -> WalkResult:
    """Helper to walk a directory with default config."""
    return walk_directory(path, FieldCheckConfig())


def test_compute_hashes_all_unique(tmp_corpus: Path) -> None:
    """All files in standard corpus should have unique hashes."""
    result = compute_hashes(_walk(tmp_corpus))
    assert result.duplicate_groups == []
    assert result.duplicate_bytes == 0
    assert result.duplicate_file_count == 0
    assert result.duplicate_percentage == 0.0


def test_compute_hashes_finds_duplicates(
    tmp_corpus_with_duplicates: Path,
) -> None:
    """Should find 2 duplicate groups: 3 text files and 2 binary files."""
    result = compute_hashes(_walk(tmp_corpus_with_duplicates))
    assert len(result.duplicate_groups) == 2

    group_sizes = sorted(len(g.paths) for g in result.duplicate_groups)
    assert group_sizes == [2, 3]


def test_compute_hashes_wasted_bytes(
    tmp_corpus_with_duplicates: Path,
) -> None:
    """Wasted bytes should be size * (copies - 1) for each group."""
    result = compute_hashes(_walk(tmp_corpus_with_duplicates))

    expected_wasted = sum(g.size * (len(g.paths) - 1) for g in result.duplicate_groups)
    assert result.duplicate_bytes == expected_wasted
    assert result.duplicate_bytes > 0


def test_compute_hashes_duplicate_percentage(
    tmp_corpus_with_duplicates: Path,
) -> None:
    """Duplicate percentage should be duplicate_file_count / total * 100."""
    result = compute_hashes(_walk(tmp_corpus_with_duplicates))
    # 5 out of 6 files are in duplicate groups (3 text + 2 binary)
    assert result.duplicate_file_count == 5
    expected_pct = 5 / result.total_hashed * 100
    assert abs(result.duplicate_percentage - expected_pct) < 0.01


def test_compute_hashes_empty_walk() -> None:
    """Empty WalkResult should return zeroed DedupResult."""
    result = compute_hashes(WalkResult())
    assert result.total_hashed == 0
    assert result.hash_errors == 0
    assert result.unique_files == 0
    assert result.duplicate_groups == []


def test_compute_hashes_progress_callback(tmp_corpus: Path) -> None:
    """Progress callback should be called once per file."""
    calls: list[tuple[int, int]] = []

    def callback(current: int, total: int) -> None:
        calls.append((current, total))

    walk = _walk(tmp_corpus)
    compute_hashes(walk, progress_callback=callback)

    assert len(calls) == len(walk.files)
    # Last call should have current == total
    assert calls[-1][0] == calls[-1][1]


def test_hash_deterministic(tmp_path: Path) -> None:
    """Hashing the same content twice should produce the same result."""
    (tmp_path / "a.txt").write_text("deterministic content", encoding="utf-8")
    (tmp_path / "b.txt").write_text("deterministic content", encoding="utf-8")

    result = compute_hashes(_walk(tmp_path))
    assert len(result.duplicate_groups) == 1
    assert len(result.duplicate_groups[0].paths) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
def test_compute_hashes_permission_error(tmp_path: Path) -> None:
    """Files that can't be read should increment hash_errors."""
    import os

    (tmp_path / "readable.txt").write_text("hello", encoding="utf-8")
    unreadable = tmp_path / "unreadable.txt"
    unreadable.write_text("secret", encoding="utf-8")
    os.chmod(unreadable, 0o000)

    try:
        result = compute_hashes(_walk(tmp_path))
        assert result.hash_errors == 1
        assert result.total_hashed == 1
    finally:
        os.chmod(unreadable, 0o644)
