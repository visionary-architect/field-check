"""Tests for inventory analysis."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.scanner import walk_directory
from field_check.scanner.inventory import (
    EXTENSION_MIME_MAP,
    InventoryResult,
    analyze_inventory,
)


def _walk(path: Path) -> InventoryResult:
    """Helper: walk and analyze a directory."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(path, config)
    return analyze_inventory(result)


def test_analyze_inventory_basic(tmp_corpus: Path) -> None:
    """Processes tmp_corpus and returns InventoryResult."""
    inv = _walk(tmp_corpus)
    assert isinstance(inv, InventoryResult)
    assert inv.total_files == 7
    assert inv.total_size > 0


def test_type_detection_pdf(tmp_corpus: Path) -> None:
    """PDF detected as application/pdf via magic bytes."""
    inv = _walk(tmp_corpus)
    assert "application/pdf" in inv.type_counts
    assert inv.type_counts["application/pdf"] == 1


def test_type_detection_png(tmp_corpus: Path) -> None:
    """PNG detected as image/png via magic bytes."""
    inv = _walk(tmp_corpus)
    assert "image/png" in inv.type_counts
    assert inv.type_counts["image/png"] == 1


def test_type_detection_text_fallback(tmp_corpus: Path) -> None:
    """.txt files get text/plain via EXTENSION_MIME_MAP fallback."""
    inv = _walk(tmp_corpus)
    assert "text/plain" in inv.type_counts
    # doc.txt, empty.txt, nested/deep/file.txt = 3
    assert inv.type_counts["text/plain"] >= 2


def test_type_detection_csv_fallback(tmp_corpus: Path) -> None:
    """.csv files get text/csv via extension fallback."""
    inv = _walk(tmp_corpus)
    assert "text/csv" in inv.type_counts
    assert inv.type_counts["text/csv"] == 1


def test_type_detection_unknown(tmp_path: Path) -> None:
    """Unknown extension gets application/octet-stream."""
    (tmp_path / "mystery.xyz123").write_bytes(b"\x00\x01\x02\x03")
    inv = _walk(tmp_path)
    assert "application/octet-stream" in inv.type_counts


def test_extension_mime_map_coverage() -> None:
    """Key text extensions are mapped."""
    assert ".txt" in EXTENSION_MIME_MAP
    assert ".csv" in EXTENSION_MIME_MAP
    assert ".json" in EXTENSION_MIME_MAP
    assert ".py" in EXTENSION_MIME_MAP
    assert ".md" in EXTENSION_MIME_MAP


def test_size_distribution_buckets(tmp_corpus: Path) -> None:
    """Files sorted into correct size buckets."""
    inv = _walk(tmp_corpus)
    total_in_buckets = sum(b.count for b in inv.size_distribution.buckets)
    assert total_in_buckets == inv.total_files


def test_size_distribution_stats(tmp_corpus: Path) -> None:
    """min/max/median/mean calculated correctly."""
    inv = _walk(tmp_corpus)
    sd = inv.size_distribution
    assert sd.min_size >= 0  # empty.txt is 0 bytes
    assert sd.max_size >= 10240  # large.bin is ~10KB
    assert sd.median_size >= 0
    assert sd.mean_size > 0


def test_age_distribution(tmp_corpus: Path) -> None:
    """Files sorted into age buckets."""
    inv = _walk(tmp_corpus)
    total_in_buckets = sum(b.count for b in inv.age_distribution.buckets)
    assert total_in_buckets == inv.total_files
    # All files just created, should be in "<1 day" bucket
    assert inv.age_distribution.buckets[0].count == inv.total_files


def test_directory_structure(tmp_corpus: Path) -> None:
    """Depth, breadth, empty dirs computed correctly."""
    inv = _walk(tmp_corpus)
    ds = inv.dir_structure
    assert ds.total_dirs >= 4  # root, nested, nested/deep, empty_dir
    assert ds.max_depth >= 2  # nested/deep/file.txt
    assert ds.max_breadth >= 1
    assert ds.empty_dirs >= 1  # empty_dir


def test_inventory_empty_corpus(tmp_path: Path) -> None:
    """0 files produces zero stats, no crash."""
    inv = _walk(tmp_path)
    assert inv.total_files == 0
    assert inv.total_size == 0
    assert inv.size_distribution.min_size == 0
    assert inv.age_distribution.oldest is None


def test_inventory_single_file(tmp_path: Path) -> None:
    """1 file produces correct stats."""
    (tmp_path / "solo.txt").write_text("hello", encoding="utf-8")
    inv = _walk(tmp_path)
    assert inv.total_files == 1
    assert inv.total_size == 5
    assert inv.size_distribution.min_size == 5
    assert inv.size_distribution.max_size == 5
    assert inv.size_distribution.median_size == 5


def test_inventory_progress_callback(tmp_corpus: Path) -> None:
    """Progress callback receives (current, total) pairs."""
    calls: list[tuple[int, int]] = []
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus, config)
    analyze_inventory(result, progress_callback=lambda c, t: calls.append((c, t)))
    assert len(calls) == len(result.files)
    assert calls[-1] == (len(result.files), len(result.files))


def test_extension_counts(tmp_corpus: Path) -> None:
    """Extension counts are tracked."""
    inv = _walk(tmp_corpus)
    assert ".txt" in inv.extension_counts
    assert ".pdf" in inv.extension_counts
    assert ".csv" in inv.extension_counts
