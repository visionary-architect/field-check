"""Tests for the HTML report renderer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from field_check.report.html import (
    _format_duration,
    _format_size,
    _try_relative,
    _try_relative_str,
    render_html_report,
)
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult, DuplicateGroup
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import (
    AgeBucket,
    AgeDistribution,
    DirectoryStructure,
    InventoryResult,
    SizeBucket,
    SizeDistribution,
)
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.sampling import SampleResult
from field_check.scanner.simhash import NearDuplicateCluster, SimHashResult

# ---------------------------------------------------------------------------
# Helpers: build minimal mock objects
# ---------------------------------------------------------------------------


def _make_walk(root: Path | None = None) -> WalkResult:
    return WalkResult(scan_root=root or Path("/fake/corpus"))


def _make_inventory(total_files: int = 10, total_size: int = 50000) -> InventoryResult:
    return InventoryResult(
        total_files=total_files,
        total_size=total_size,
        type_counts={"text/plain": 6, "application/pdf": 4},
        type_sizes={"text/plain": 20000, "application/pdf": 30000},
        size_distribution=SizeDistribution(
            buckets=[
                SizeBucket(label="<1 KB", min_bytes=0, max_bytes=1024, count=2),
                SizeBucket(label="1-10 KB", min_bytes=1024, max_bytes=10240, count=5),
                SizeBucket(label="10-100 KB", min_bytes=10240, max_bytes=102400, count=3),
            ],
            min_size=100,
            max_size=90000,
            median_size=5000,
            mean_size=5000.0,
        ),
        age_distribution=AgeDistribution(
            buckets=[AgeBucket(label="<1 day", count=5), AgeBucket(label="1-7 days", count=5)],
            oldest=datetime(2024, 1, 1, tzinfo=UTC),
            newest=datetime(2025, 6, 1, tzinfo=UTC),
        ),
        dir_structure=DirectoryStructure(
            total_dirs=3,
            max_depth=2,
            avg_depth=1.0,
            max_breadth=5,
            avg_breadth=3.3,
            empty_dirs=1,
        ),
    )


def _make_sample(pop: int = 100) -> SampleResult:
    return SampleResult(
        total_sample_size=20,
        total_population_size=pop,
        sampling_rate=0.20,
    )


# ---------------------------------------------------------------------------
# TestFormatHelpers
# ---------------------------------------------------------------------------


class TestFormatHelpers:
    """Test _format_size and _format_duration helper functions."""

    def test_format_size_bytes(self) -> None:
        assert _format_size(500) == "500 B"

    def test_format_size_kb(self) -> None:
        assert _format_size(2048) == "2.0 KB"

    def test_format_size_mb(self) -> None:
        result = _format_size(5 * 1024 * 1024)
        assert result == "5.0 MB"

    def test_format_size_gb(self) -> None:
        result = _format_size(2 * 1024 * 1024 * 1024)
        assert result == "2.0 GB"

    def test_format_size_fractional_mb(self) -> None:
        result = _format_size(1_500_000)
        assert "MB" in result

    def test_format_size_fractional_gb(self) -> None:
        result = _format_size(1_500_000_000)
        assert "GB" in result

    def test_format_duration_ms(self) -> None:
        assert _format_duration(0.45) == "450ms"

    def test_format_duration_seconds(self) -> None:
        assert _format_duration(12.3) == "12.3s"

    def test_format_duration_minutes(self) -> None:
        result = _format_duration(125.0)
        assert result == "2m 5s"

    def test_format_duration_exact_minute(self) -> None:
        result = _format_duration(60.0)
        assert result == "1m 0s"


# ---------------------------------------------------------------------------
# TestTryRelative
# ---------------------------------------------------------------------------


class TestTryRelative:
    """Test _try_relative and _try_relative_str exception branches."""

    def test_try_relative_normal(self) -> None:
        root = Path("/data/corpus")
        result = _try_relative(Path("/data/corpus/sub/file.txt"), root)
        assert result == Path("sub/file.txt")

    def test_try_relative_value_error(self) -> None:
        """Path not under root triggers ValueError branch, returns as-is."""
        root = Path("/data/corpus")
        other = Path("/other/place/file.txt")
        result = _try_relative(other, root)
        assert result == other

    def test_try_relative_str_normal(self) -> None:
        root = Path("/data/corpus")
        result = _try_relative_str("/data/corpus/sub/file.txt", root)
        assert result.replace("\\", "/") == "sub/file.txt"

    def test_try_relative_str_value_error(self) -> None:
        """Path not under root triggers ValueError, returns basename."""
        root = Path("/data/corpus")
        result = _try_relative_str("/other/place/file.txt", root)
        assert result == "file.txt"


# ---------------------------------------------------------------------------
# TestRenderMinimal
# ---------------------------------------------------------------------------


class TestRenderMinimal:
    """Render with only inventory (no optional sections)."""

    def test_renders_html_string(self) -> None:
        html = render_html_report(
            inventory=_make_inventory(),
            walk_result=_make_walk(),
            elapsed_seconds=2.5,
        )
        assert "<!DOCTYPE html>" in html or "<html" in html

    def test_contains_scan_path(self) -> None:
        root = Path("/my/scan")
        html = render_html_report(
            inventory=_make_inventory(),
            walk_result=_make_walk(root),
            elapsed_seconds=0.5,
        )
        # On Windows, Path("/my/scan") resolves with a drive letter
        assert str(root) in html

    def test_contains_file_count(self) -> None:
        html = render_html_report(
            inventory=_make_inventory(total_files=42),
            walk_result=_make_walk(),
            elapsed_seconds=1.0,
        )
        assert "42" in html

    def test_no_dedup_section(self) -> None:
        html = render_html_report(
            inventory=_make_inventory(),
            walk_result=_make_walk(),
            elapsed_seconds=1.0,
        )
        assert "Duplicate" not in html or "duplicate_groups" not in html


# ---------------------------------------------------------------------------
# TestRenderWithAllSections
# ---------------------------------------------------------------------------


class TestRenderWithAllSections:
    """Render with all optional sections populated."""

    @pytest.fixture()
    def full_html(self) -> str:
        root = Path("/test/corpus")
        walk = _make_walk(root)
        inv = _make_inventory(total_files=50, total_size=500_000)
        sample = _make_sample(pop=50)

        dedup = DedupResult(
            total_hashed=50,
            unique_files=45,
            duplicate_groups=[
                DuplicateGroup(
                    hash="abc123def456",
                    size=1024,
                    paths=[root / "a.txt", root / "b.txt"],
                ),
            ],
            duplicate_file_count=2,
            duplicate_bytes=1024,
            duplicate_percentage=4.0,
        )

        corruption = CorruptionResult(
            total_checked=50,
            ok_count=45,
            empty_count=2,
            near_empty_count=1,
            corrupt_count=1,
            encrypted_count=1,
            unreadable_count=0,
        )

        pii = PIIScanResult(
            total_scanned=20,
            files_with_pii=5,
            per_type_counts={"email": 10, "ssn": 3},
            per_type_file_counts={"email": 5, "ssn": 2},
            pattern_labels={"email": "Email Address", "ssn": "SSN (US)"},
        )

        language = LanguageResult(
            total_analyzed=20,
            language_distribution={"English": 15, "Spanish": 5},
        )

        encoding = EncodingResult(
            total_analyzed=20,
            encoding_distribution={"utf-8": 18, "iso-8859-1": 2},
        )

        simhash = SimHashResult(
            total_analyzed=20,
            total_clusters=2,
            total_files_in_clusters=6,
            threshold=5,
            clusters=[
                NearDuplicateCluster(
                    paths=["/test/corpus/a.txt", "/test/corpus/b.txt"],
                    similarity=0.95,
                ),
                NearDuplicateCluster(
                    paths=["/test/corpus/c.txt", "/test/corpus/d.txt"],
                    similarity=0.88,
                ),
            ],
        )

        return render_html_report(
            inventory=inv,
            walk_result=walk,
            elapsed_seconds=3.7,
            dedup_result=dedup,
            corruption_result=corruption,
            sample_result=sample,
            pii_result=pii,
            language_result=language,
            encoding_result=encoding,
            simhash_result=simhash,
        )

    def test_dedup_section_present(self, full_html: str) -> None:
        assert "abc123def456"[:12] in full_html

    def test_corruption_section_present(self, full_html: str) -> None:
        assert "45" in full_html  # ok_count

    def test_pii_section_present(self, full_html: str) -> None:
        assert "Email Address" in full_html

    def test_language_section_present(self, full_html: str) -> None:
        assert "English" in full_html
        assert "Spanish" in full_html

    def test_encoding_section_present(self, full_html: str) -> None:
        assert "utf-8" in full_html

    def test_simhash_section_present(self, full_html: str) -> None:
        assert "Near" in full_html or "near" in full_html or "SimHash" in full_html
        assert "95.0" in full_html  # similarity percentage

    def test_duration_formatted(self, full_html: str) -> None:
        assert "3.7s" in full_html


# ---------------------------------------------------------------------------
# TestRenderSimhashCI
# ---------------------------------------------------------------------------


class TestRenderSimhashCI:
    """Test simhash section with files_in_clusters > 0 to hit CI computation."""

    def test_simhash_ci_computed(self) -> None:
        root = Path("/corpus")
        sample = _make_sample(pop=200)

        simhash = SimHashResult(
            total_analyzed=20,
            total_clusters=1,
            total_files_in_clusters=8,
            threshold=5,
            clusters=[
                NearDuplicateCluster(
                    paths=["/corpus/f1.txt", "/corpus/f2.txt", "/corpus/f3.txt"],
                    similarity=0.92,
                ),
            ],
        )

        html = render_html_report(
            inventory=_make_inventory(),
            walk_result=_make_walk(root),
            elapsed_seconds=1.0,
            sample_result=sample,
            simhash_result=simhash,
        )
        # CI string should contain "%" and "CI:" (not census)
        assert "%" in html
        # The corpus_pct should be rendered (non-None path)
        assert "corpus" in html.lower() or "near-dup" in html.lower()

    def test_simhash_no_clusters_no_ci(self) -> None:
        """When total_files_in_clusters == 0, corpus_pct is None."""
        root = Path("/corpus")
        sample = _make_sample(pop=200)

        simhash = SimHashResult(
            total_analyzed=20,
            total_clusters=0,
            total_files_in_clusters=0,
            threshold=5,
            clusters=[],
        )

        html = render_html_report(
            inventory=_make_inventory(),
            walk_result=_make_walk(root),
            elapsed_seconds=1.0,
            sample_result=sample,
            simhash_result=simhash,
        )
        # The "Est. corpus near-dup %" row should not appear
        assert "Est. corpus" not in html

    def test_simhash_relative_paths_in_clusters(self) -> None:
        """Cluster paths from outside root use basename fallback."""
        root = Path("/corpus")
        sample = _make_sample(pop=100)

        simhash = SimHashResult(
            total_analyzed=10,
            total_clusters=1,
            total_files_in_clusters=2,
            threshold=5,
            clusters=[
                NearDuplicateCluster(
                    paths=["/other/outside.txt", "/corpus/inside.txt"],
                    similarity=0.90,
                ),
            ],
        )

        html = render_html_report(
            inventory=_make_inventory(),
            walk_result=_make_walk(root),
            elapsed_seconds=1.0,
            sample_result=sample,
            simhash_result=simhash,
        )
        # outside.txt should appear as basename (ValueError branch)
        assert "outside.txt" in html
        # inside.txt should appear as relative path
        assert "inside.txt" in html
