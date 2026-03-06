"""Tests for the Rich terminal report renderer — 100 % coverage target."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from field_check.report.terminal import (
    _bar,
    _format_duration,
    _format_size,
    render_terminal_report,
)
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult, FileHealth
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
from field_check.scanner.pii import PIIFileResult, PIIMatch, PIIScanResult
from field_check.scanner.sampling import SampleResult
from field_check.scanner.simhash import NearDuplicateCluster, SimHashResult
from field_check.scanner.text import TextExtractionResult

ROOT = Path("/test/corpus")


def _cap() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=200, no_color=True), buf


def _inv(**kw) -> InventoryResult:
    d = dict(
        total_files=10,
        total_size=50_000,
        type_counts={"application/pdf": 5, "text/plain": 5},
        type_sizes={"application/pdf": 30_000, "text/plain": 20_000},
        size_distribution=SizeDistribution(
            buckets=[SizeBucket("1-10 KB", 1024, 10240, count=10)],
            min_size=1024,
            max_size=9000,
            median_size=5000,
            mean_size=5000.0,
        ),
        age_distribution=AgeDistribution(
            buckets=[AgeBucket("<1 day", count=10)],
            oldest=datetime(2024, 1, 1, tzinfo=UTC),
            newest=datetime(2026, 3, 1, tzinfo=UTC),
        ),
        dir_structure=DirectoryStructure(
            total_dirs=3, max_depth=2, avg_depth=1.0, max_breadth=5, avg_breadth=3.0, empty_dirs=0
        ),
    )
    d.update(kw)
    return InventoryResult(**d)


def _walk(root: Path = ROOT) -> WalkResult:
    return WalkResult(scan_root=root)


def _samp(**kw) -> SampleResult:
    d = dict(
        total_population_size=100, sampling_rate=0.5, per_type_population={"application/pdf": 50}
    )
    d.update(kw)
    return SampleResult(**d)


def _render(inv=None, walk=None, dur=1.0, **sections):
    c, buf = _cap()
    render_terminal_report(inv or _inv(), walk or _walk(), dur, c, **sections)
    return buf.getvalue()


# ---- pure helpers ---------------------------------------------------------


class TestFormatHelpers:
    def test_format_size_all_branches(self):
        assert _format_size(500) == "500 B"
        assert _format_size(2048) == "2.0 KB"
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"
        assert _format_size(3 * 1024**3) == "3.0 GB"

    def test_format_duration_all_branches(self):
        assert _format_duration(0.5) == "500ms"
        assert _format_duration(12.3) == "12.3s"
        assert _format_duration(125) == "2m 5s"

    def test_bar(self):
        assert _bar(1.0, 10) == "##########"
        assert _bar(0.0, 10) == "----------"
        assert _bar(0.5, 10) == "#####-----"


# ---- type distribution ---------------------------------------------------


class TestTypeDistribution:
    def test_empty_types(self):
        assert "File Type Distribution" not in _render(inv=_inv(type_counts={}))

    def test_normal(self):
        out = _render()
        assert "application/pdf" in out and "text/plain" in out

    def test_overflow_gt15(self):
        types = {f"type/t{i}": i + 1 for i in range(18)}
        sizes = {f"type/t{i}": (i + 1) * 100 for i in range(18)}
        out = _render(
            inv=_inv(type_counts=types, type_sizes=sizes, total_files=sum(types.values()))
        )
        assert "Other" in out and "3 types" in out


# ---- size / age distribution ---------------------------------------------


class TestDistributions:
    def test_size_empty_buckets(self):
        assert "Size Distribution" not in _render(
            inv=_inv(size_distribution=SizeDistribution(buckets=[]))
        )

    def test_size_normal(self):
        out = _render()
        assert "Size Distribution" in out and "Min:" in out

    def test_age_empty_buckets(self):
        assert "File Age Distribution" not in _render(
            inv=_inv(age_distribution=AgeDistribution(buckets=[]))
        )

    def test_age_with_dates(self):
        out = _render()
        assert "Oldest:" in out and "2024-01-01" in out


# ---- directory structure --------------------------------------------------


class TestDirStructure:
    def test_no_empty(self):
        assert "Empty directories" not in _render()

    def test_with_empty(self):
        ds = DirectoryStructure(
            total_dirs=5, max_depth=3, avg_depth=1.5, max_breadth=10, avg_breadth=4.0, empty_dirs=2
        )
        assert "Empty directories" in _render(inv=_inv(dir_structure=ds))


# ---- issues section -------------------------------------------------------


class TestIssues:
    def test_none(self):
        assert "Issues" not in _render()

    def test_all_issue_types(self):
        out = _render(
            inv=_inv(permission_errors=3, symlink_loops=1, type_detection_errors=2),
            dedup_result=DedupResult(hash_errors=4),
            text_result=TextExtractionResult(extraction_errors=5, timeout_errors=1),
            pii_result=PIIScanResult(scan_errors=2),
        )
        for label in (
            "Permission errors",
            "Symlink loops",
            "Type detection errors",
            "Hash errors",
            "Extraction errors",
            "Extraction timeouts",
            "PII scan errors",
        ):
            assert label in out


# ---- dedup summary --------------------------------------------------------


class TestDedupSummary:
    def test_no_groups(self):
        out = _render(dedup_result=DedupResult(total_hashed=50, unique_files=50))
        assert "Duplicate Detection" in out
        assert "Top Duplicate Groups" not in out

    def test_with_groups(self):
        grp = DuplicateGroup(
            hash="abcdef1234567890", size=1024, paths=[Path(f"/{c}.txt") for c in "abcd"]
        )
        out = _render(
            dedup_result=DedupResult(
                total_hashed=10,
                unique_files=7,
                duplicate_groups=[grp],
                duplicate_file_count=4,
                duplicate_bytes=3072,
                duplicate_percentage=40.0,
            )
        )
        assert "Top Duplicate Groups" in out
        assert "abcdef123456" in out and "... and 1 more" in out


# ---- corruption summary ---------------------------------------------------


class TestCorruptionSummary:
    def test_all_statuses(self):
        out = _render(
            walk=_walk(ROOT),
            corruption_result=CorruptionResult(
                total_checked=10,
                ok_count=4,
                empty_count=1,
                near_empty_count=1,
                corrupt_count=1,
                encrypted_count=1,
                unreadable_count=1,
                flagged_files=[
                    FileHealth(ROOT / "e.txt", "empty", "", "0 bytes"),
                    FileHealth(ROOT / "c.pdf", "corrupt", "application/pdf", "Hdr"),
                    FileHealth(ROOT / "enc.pdf", "encrypted_pdf", "application/pdf", "Enc"),
                ],
            ),
        )
        for word in ("Corrupt", "Encrypted", "Unreadable", "Flagged Files", "e.txt"):
            assert word in out

    def test_gt20_overflow(self):
        flagged = [FileHealth(ROOT / f"f{i}.txt", "empty", "", "0B") for i in range(25)]
        out = _render(
            walk=_walk(ROOT),
            corruption_result=CorruptionResult(
                total_checked=30, ok_count=5, empty_count=25, flagged_files=flagged
            ),
        )
        assert "... and 5 more flagged files" in out

    def test_path_outside_root(self):
        out = _render(
            walk=_walk(ROOT),
            corruption_result=CorruptionResult(
                total_checked=5,
                ok_count=4,
                empty_count=1,
                flagged_files=[FileHealth(Path("/other/file.txt"), "empty", "", "0B")],
            ),
        )
        assert "file.txt" in out


# ---- text analysis --------------------------------------------------------


class TestTextAnalysis:
    def test_zero_processed(self):
        assert "Document Content Analysis" not in _render(
            text_result=TextExtractionResult(total_processed=0), sample_result=_samp()
        )

    def test_extraction_errors(self):
        assert "Extraction errors" in _render(
            text_result=TextExtractionResult(
                total_processed=10, extraction_errors=2, native_count=8
            ),
            sample_result=_samp(),
        )

    def test_scanned_native_mixed(self):
        out = _render(
            text_result=TextExtractionResult(
                total_processed=10, native_count=5, scanned_count=3, mixed_scan_count=2
            ),
            sample_result=_samp(),
        )
        assert "Scanned PDF Detection" in out and "Native" in out

    def test_scanned_zero_classified(self):
        assert "Scanned PDF Detection" not in _render(
            text_result=TextExtractionResult(
                total_processed=5, text_heavy_count=3, image_heavy_count=2
            ),
            sample_result=_samp(),
        )

    def test_content_classification_pop_fallback(self):
        assert "Content Classification" in _render(
            text_result=TextExtractionResult(
                total_processed=5,
                extraction_errors=5,
                native_count=5,
                text_heavy_count=3,
                image_heavy_count=2,
            ),
            sample_result=_samp(),
        )

    def test_content_classification(self):
        out = _render(
            text_result=TextExtractionResult(
                total_processed=10,
                text_heavy_count=5,
                image_heavy_count=3,
                mixed_content_count=2,
                native_count=10,
            ),
            sample_result=_samp(),
        )
        assert "Content Classification" in out and "Text-heavy" in out

    def test_metadata(self):
        out = _render(
            text_result=TextExtractionResult(
                total_processed=10,
                native_count=10,
                metadata_total_checked=10,
                metadata_field_counts={"title": 8, "author": 5, "creation_date": 3},
            ),
            sample_result=_samp(),
        )
        assert "Metadata Completeness" in out and "Title" in out

    def test_page_counts(self):
        out = _render(
            text_result=TextExtractionResult(
                total_processed=10,
                native_count=10,
                page_count_distribution={"1 page": 3, "2-5 pages": 5, "6-10 pages": 2},
                page_count_total=30,
                page_count_min=1,
                page_count_max=10,
            ),
            sample_result=_samp(),
        )
        assert "Page Count Distribution" in out and "Min:" in out


# ---- PII ------------------------------------------------------------------


class TestPII:
    def test_no_pii(self):
        assert "No PII risk indicators found" in _render(
            pii_result=PIIScanResult(total_scanned=10), sample_result=_samp()
        )

    def test_zero_scanned(self):
        assert "PII Risk Indicators" not in _render(
            pii_result=PIIScanResult(total_scanned=0), sample_result=_samp()
        )

    def test_per_type_breakdown(self):
        out = _render(
            pii_result=PIIScanResult(
                total_scanned=20,
                files_with_pii=5,
                per_type_counts={"email": 10, "ssn": 3},
                per_type_file_counts={"email": 5, "ssn": 2},
                pattern_labels={"email": "Email Address", "ssn": "SSN (US)"},
                pattern_fp_rates={"email": 0.10, "ssn": 0.40},
                scan_errors=1,
            ),
            sample_result=_samp(),
        )
        for t in ("Email Address", "SSN (US)", "Scan errors", "Total matches", "Expected FP rate"):
            assert t in out

    def test_warning_banner(self):
        assert "Privacy Warning" in _render(
            pii_result=PIIScanResult(
                total_scanned=10,
                files_with_pii=1,
                per_type_counts={"email": 1},
                per_type_file_counts={"email": 1},
                pattern_labels={"email": "Email"},
                pattern_fp_rates={"email": 0.1},
                show_pii_samples=True,
            ),
            sample_result=_samp(),
        )


# ---- language / encoding --------------------------------------------------


class TestLanguageEncoding:
    def test_language_gt10_overflow(self):
        langs = {f"Lang{i}": i + 1 for i in range(12)}
        out = _render(
            language_result=LanguageResult(
                total_analyzed=sum(langs.values()), language_distribution=langs
            ),
            sample_result=_samp(),
        )
        assert "Other" in out and "2 languages" in out

    def test_encoding(self):
        out = _render(
            encoding_result=EncodingResult(
                total_analyzed=10, encoding_distribution={"utf-8": 8, "iso-8859-1": 2}
            )
        )
        assert "Encoding Distribution" in out and "utf-8" in out

    def test_detection_errors(self):
        assert "Detection errors: 3" in _render(
            language_result=LanguageResult(
                total_analyzed=5, language_distribution={"English": 4}, detection_errors=3
            ),
            sample_result=_samp(),
        )


# ---- near-duplicates ------------------------------------------------------


class TestNearDuplicates:
    def test_summary_ci(self):
        out = _render(
            simhash_result=SimHashResult(
                total_analyzed=50, total_clusters=2, total_files_in_clusters=6, threshold=5
            ),
            sample_result=_samp(),
        )
        assert "Near-Duplicate Detection" in out and "CI:" in out

    def test_cluster_detail(self):
        cluster = NearDuplicateCluster(
            paths=[str(ROOT / f"{c}.txt") for c in "abcdef"], similarity=0.92
        )
        out = _render(
            walk=_walk(ROOT),
            simhash_result=SimHashResult(
                total_analyzed=50,
                total_clusters=1,
                total_files_in_clusters=6,
                threshold=5,
                clusters=[cluster],
            ),
            sample_result=_samp(),
        )
        assert "Top Near-Duplicate Clusters" in out
        assert "92.0%" in out and "... and 1 more" in out

    def test_path_outside_root(self):
        cluster = NearDuplicateCluster(
            paths=["/elsewhere/a.txt", "/elsewhere/b.txt"], similarity=0.88
        )
        out = _render(
            walk=_walk(ROOT),
            simhash_result=SimHashResult(
                total_analyzed=50,
                total_clusters=1,
                total_files_in_clusters=2,
                threshold=5,
                clusters=[cluster],
            ),
            sample_result=_samp(),
        )
        assert "a.txt" in out and "b.txt" in out

    def test_zero_analyzed(self):
        assert "Near-Duplicate Detection" not in _render(
            simhash_result=SimHashResult(total_analyzed=0), sample_result=_samp()
        )


# ---- PII samples ----------------------------------------------------------


class TestPIISamples:
    def _pii_with_samples(self, matches):
        fr = PIIFileResult(
            path="/test/doc.txt", matches_by_type={"email": len(matches)}, sample_matches=matches
        )
        return PIIScanResult(
            total_scanned=10,
            files_with_pii=1,
            per_type_counts={"email": len(matches)},
            per_type_file_counts={"email": 1},
            pattern_labels={"email": "Email Address"},
            pattern_fp_rates={"email": 0.10},
            file_results=[fr],
            show_pii_samples=True,
        )

    def test_rendering(self):
        matches = [PIIMatch("email", "a@b.com", 5), PIIMatch("email", "c@d.org", 12)]
        out = _render(pii_result=self._pii_with_samples(matches), sample_result=_samp())
        assert "PII Samples" in out and "a@b.com" in out

    def test_gt20_overflow(self):
        matches = [PIIMatch("email", f"u{i}@x.com", i) for i in range(25)]
        out = _render(pii_result=self._pii_with_samples(matches), sample_result=_samp())
        assert "... and 5 more matches" in out


# ---- full integration test ------------------------------------------------


class TestFullReport:
    def test_all_sections(self):
        dedup = DedupResult(
            total_hashed=10,
            unique_files=8,
            duplicate_groups=[DuplicateGroup("abc", 500, [Path("/a"), Path("/b")])],
            duplicate_file_count=2,
            duplicate_bytes=500,
            duplicate_percentage=20.0,
        )
        corruption = CorruptionResult(
            total_checked=10,
            ok_count=9,
            corrupt_count=1,
            flagged_files=[
                FileHealth(ROOT / "bad.pdf", "corrupt", "application/pdf", "Bad header")
            ],
        )
        text = TextExtractionResult(
            total_processed=10, native_count=10, text_heavy_count=8, image_heavy_count=2
        )
        out = _render(
            inv=_inv(
                dir_structure=DirectoryStructure(
                    total_dirs=5,
                    max_depth=3,
                    avg_depth=1.5,
                    max_breadth=10,
                    avg_breadth=4.0,
                    empty_dirs=1,
                )
            ),
            walk=_walk(ROOT),
            dur=65.5,
            dedup_result=dedup,
            corruption_result=corruption,
            sample_result=_samp(),
            text_result=text,
            pii_result=PIIScanResult(total_scanned=10),
            language_result=LanguageResult(
                total_analyzed=10, language_distribution={"English": 10}
            ),
            encoding_result=EncodingResult(total_analyzed=5, encoding_distribution={"utf-8": 5}),
            simhash_result=SimHashResult(
                total_analyzed=10,
                total_clusters=1,
                total_files_in_clusters=3,
                threshold=5,
                clusters=[NearDuplicateCluster([str(ROOT / "x.txt"), str(ROOT / "y.txt")], 0.95)],
            ),
        )
        for section in (
            "Field Check",
            "Duplicate Detection",
            "File Health",
            "No PII risk indicators found",
            "Language Distribution",
            "Encoding Distribution",
            "Near-Duplicate Detection",
            "No data transmitted",
        ):
            assert section in out
