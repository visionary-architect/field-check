"""Tests for stratified sampling and confidence interval calculation."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.scanner import FileEntry, WalkResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.sampling import (
    SampleResult,
    compute_confidence_interval,
    format_ci,
    select_sample,
)


def _make_walk_and_inventory(
    tmp_path: Path,
    file_specs: list[tuple[str, str, int]],
) -> tuple[WalkResult, InventoryResult]:
    """Helper to create WalkResult and InventoryResult from file specs.

    Args:
        tmp_path: Base directory for files.
        file_specs: List of (filename, mime_type, size) tuples.
    """
    walk = WalkResult(scan_root=tmp_path)
    file_types: dict[Path, str] = {}

    for name, mime, size in file_specs:
        fpath = tmp_path / name
        fpath.write_bytes(b"x" * size)
        entry = FileEntry(
            path=fpath,
            relative_path=Path(name),
            size=size,
            mtime=0.0,
            ctime=0.0,
            is_symlink=False,
        )
        walk.files.append(entry)
        walk.total_size += size
        file_types[fpath] = mime

    inventory = InventoryResult(
        total_files=len(walk.files),
        total_size=walk.total_size,
        file_types=file_types,
    )
    return walk, inventory


def test_select_sample_basic(tmp_path: Path) -> None:
    """Basic sampling selects a subset of files."""
    specs = [(f"file{i}.txt", "text/plain", 100) for i in range(100)]
    walk, inv = _make_walk_and_inventory(tmp_path, specs)
    config = FieldCheckConfig(sampling_rate=0.10, sampling_min_per_type=5)

    result = select_sample(walk, inv, config)

    assert isinstance(result, SampleResult)
    assert result.total_population_size == 100
    assert result.total_sample_size >= 10  # 10% of 100
    assert result.total_sample_size <= 100
    assert not result.is_census


def test_select_sample_min_per_type(tmp_path: Path) -> None:
    """Min per type forces selecting all files when fewer than minimum."""
    specs = [(f"doc{i}.pdf", "application/pdf", 200) for i in range(10)]
    walk, inv = _make_walk_and_inventory(tmp_path, specs)
    config = FieldCheckConfig(sampling_rate=0.10, sampling_min_per_type=30)

    result = select_sample(walk, inv, config)

    # min_per_type=30 but only 10 files, so takes all
    assert result.total_sample_size == 10
    assert result.is_census


def test_select_sample_census(tmp_path: Path) -> None:
    """Rate 1.0 selects all files."""
    specs = [
        ("a.txt", "text/plain", 100),
        ("b.pdf", "application/pdf", 200),
        ("c.csv", "text/csv", 50),
    ]
    walk, inv = _make_walk_and_inventory(tmp_path, specs)
    config = FieldCheckConfig(sampling_rate=1.0)

    result = select_sample(walk, inv, config)

    assert result.total_sample_size == 3
    assert result.is_census


def test_select_sample_stratified(tmp_path: Path) -> None:
    """Multiple types get proportional samples."""
    specs = (
        [(f"pdf{i}.pdf", "application/pdf", 200) for i in range(50)]
        + [(f"txt{i}.txt", "text/plain", 100) for i in range(50)]
    )
    walk, inv = _make_walk_and_inventory(tmp_path, specs)
    config = FieldCheckConfig(sampling_rate=0.20, sampling_min_per_type=5)

    result = select_sample(walk, inv, config)

    # Both types should be represented
    assert "application/pdf" in result.per_type_sample
    assert "text/plain" in result.per_type_sample
    assert len(result.per_type_sample["application/pdf"]) >= 10
    assert len(result.per_type_sample["text/plain"]) >= 10


def test_select_sample_empty_walk(tmp_path: Path) -> None:
    """Empty WalkResult returns empty sample."""
    walk = WalkResult(scan_root=tmp_path)
    inv = InventoryResult()
    config = FieldCheckConfig()

    result = select_sample(walk, inv, config)

    assert result.total_sample_size == 0
    assert result.selected_files == []


def test_confidence_interval_basic() -> None:
    """CI for 50% proportion with reasonable sample size."""
    ci = compute_confidence_interval(50, 100, 1000)

    assert ci.point_estimate == 0.5
    assert ci.lower < 0.5
    assert ci.upper > 0.5
    assert ci.lower > 0.0
    assert ci.upper < 1.0
    assert ci.confidence_level == 0.95
    assert ci.sample_size == 100
    assert ci.population_size == 1000


def test_confidence_interval_census() -> None:
    """Census (n >= N) returns exact values with zero margin."""
    ci = compute_confidence_interval(30, 100, 100)

    assert ci.point_estimate == 0.3
    assert ci.lower == 0.3
    assert ci.upper == 0.3


def test_confidence_interval_small_sample() -> None:
    """Small sample produces wider intervals."""
    ci_small = compute_confidence_interval(5, 10, 1000)
    ci_large = compute_confidence_interval(50, 100, 1000)

    # Both have ~50% proportion, but small sample should be wider
    small_width = ci_small.upper - ci_small.lower
    large_width = ci_large.upper - ci_large.lower
    assert small_width > large_width


def test_confidence_interval_zero_successes() -> None:
    """Zero successes returns valid CI with lower >= 0."""
    ci = compute_confidence_interval(0, 100, 1000)

    assert ci.point_estimate == 0.0
    assert ci.lower >= 0.0
    assert ci.upper > 0.0  # Wilson score gives non-zero upper even at 0


def test_confidence_interval_all_successes() -> None:
    """All successes returns valid CI with upper <= 1."""
    ci = compute_confidence_interval(100, 100, 1000)

    assert ci.point_estimate == 1.0
    assert ci.upper <= 1.0
    assert ci.lower < 1.0  # Wilson score gives < 1 lower even at 100%


def test_confidence_interval_zero_sample() -> None:
    """Zero sample size returns zeros."""
    ci = compute_confidence_interval(0, 0, 100)

    assert ci.point_estimate == 0.0
    assert ci.lower == 0.0
    assert ci.upper == 0.0


def test_format_ci_sampled() -> None:
    """Format string includes CI range for sampled data."""
    ci = compute_confidence_interval(50, 100, 1000)
    formatted = format_ci(ci)

    assert "50.0%" in formatted
    assert "CI:" in formatted
    assert "n=100" in formatted


def test_format_ci_census() -> None:
    """Format string shows 'exact' for census data."""
    ci = compute_confidence_interval(30, 100, 100)
    formatted = format_ci(ci)

    assert "30.0%" in formatted
    assert "exact" in formatted
    assert "N=100" in formatted
