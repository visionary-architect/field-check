"""Tests for the directory walker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from field_check.config import FieldCheckConfig
from field_check.scanner import walk_directory


def test_walk_basic(tmp_corpus: Path) -> None:
    """Walks tmp_corpus and finds expected file count."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus, config)
    # doc.txt, report.pdf, data.csv, image.png, empty.txt, nested/deep/file.txt, large.bin
    assert len(result.files) == 7


def test_walk_file_entries(tmp_corpus: Path) -> None:
    """FileEntry fields are populated correctly."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus, config)

    by_name = {f.relative_path.name: f for f in result.files}
    doc = by_name["doc.txt"]
    assert doc.size > 0
    assert doc.mtime > 0
    assert doc.ctime > 0
    assert doc.is_symlink is False
    assert doc.path.is_absolute()


def test_walk_total_size(tmp_corpus: Path) -> None:
    """Total size is sum of all file sizes."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus, config)
    assert result.total_size == sum(f.size for f in result.files)


def test_walk_excludes_patterns(tmp_corpus: Path) -> None:
    """Config excludes filter out matching files/dirs."""
    config = FieldCheckConfig(exclude=["*.bin", "nested"])
    result = walk_directory(tmp_corpus, config)
    names = {f.relative_path.name for f in result.files}
    assert "large.bin" not in names
    assert "file.txt" not in names  # inside nested/


def test_walk_excludes_via_config_file(tmp_corpus_with_config: Path) -> None:
    """Excludes loaded from .field-check.yaml work."""
    from field_check.config import load_config

    config = load_config(tmp_corpus_with_config)
    result = walk_directory(tmp_corpus_with_config, config)
    names = {f.relative_path.name for f in result.files}
    assert "large.bin" not in names


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin on Windows")
def test_walk_symlink_detection(tmp_corpus_with_symlinks: Path) -> None:
    """Symlinks are detected (is_symlink=True)."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus_with_symlinks, config)
    by_name = {f.relative_path.name: f for f in result.files}
    assert "link_to_doc.txt" in by_name
    assert by_name["link_to_doc.txt"].is_symlink is True


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin on Windows")
def test_walk_symlink_loop(tmp_corpus_with_symlinks: Path) -> None:
    """Symlink loop detected and reported, doesn't hang."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus_with_symlinks, config)
    assert len(result.symlink_loops) > 0


def test_walk_empty_directory(tmp_path: Path) -> None:
    """Empty dir produces 0 files, no crash."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_path, config)
    assert len(result.files) == 0
    assert result.total_size == 0


def test_walk_nonexistent_path() -> None:
    """Raises FileNotFoundError for nonexistent path."""
    config = FieldCheckConfig(exclude=[])
    with pytest.raises(FileNotFoundError):
        walk_directory(Path("/nonexistent/path/xyz"), config)


def test_walk_single_file(tmp_path: Path) -> None:
    """Scanning a single file (not a directory) raises NotADirectoryError."""
    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")
    config = FieldCheckConfig(exclude=[])
    with pytest.raises(NotADirectoryError):
        walk_directory(f, config)


def test_walk_progress_callback(tmp_corpus: Path) -> None:
    """Progress callback is invoked with incrementing counts."""
    counts: list[int] = []
    config = FieldCheckConfig(exclude=[])
    walk_directory(tmp_corpus, config, progress_callback=lambda c: counts.append(c))
    assert len(counts) > 0
    assert counts == sorted(counts)  # monotonically increasing
    assert counts[-1] == len(counts)  # count matches number of calls


def test_walk_excluded_count(tmp_corpus: Path) -> None:
    """excluded_count reflects filtered items."""
    config = FieldCheckConfig(exclude=["*.bin", "*.pdf"])
    result = walk_directory(tmp_corpus, config)
    assert result.excluded_count >= 2  # at least large.bin and report.pdf


def test_walk_tracks_directories(tmp_corpus: Path) -> None:
    """total_dirs and empty_dirs counted correctly."""
    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_corpus, config)
    # root, nested, nested/deep, empty_dir = at least 4
    assert result.total_dirs >= 4
    # empty_dir has no files
    assert result.empty_dirs >= 1


def test_walk_empty_dir_counting(tmp_path: Path) -> None:
    """Dir with only subdirs (no files) counts as empty."""
    # Create dir with only a subdirectory, no files
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()
    (child / "file.txt").write_text("content", encoding="utf-8")

    config = FieldCheckConfig(exclude=[])
    result = walk_directory(tmp_path, config)

    # tmp_path has no files directly, parent has no files directly
    # child has one file
    assert result.empty_dirs >= 2  # tmp_path and parent
