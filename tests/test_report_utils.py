"""Tests for shared report utility functions."""

from __future__ import annotations

from pathlib import Path

from field_check.report.utils import (
    build_corruption_detail_lookup,
    build_duplicate_paths,
    build_encoding_lookup,
    build_hash_lookup,
    build_health_lookup,
    build_language_lookup,
    build_pii_lookup,
    format_duration,
    format_size,
    try_relative,
    try_relative_forward,
)
from field_check.scanner.corruption import CorruptionResult, FileHealth
from field_check.scanner.dedup import DedupResult, DuplicateGroup
from field_check.scanner.encoding import EncodingFileResult, EncodingResult
from field_check.scanner.language import LanguageFileResult, LanguageResult
from field_check.scanner.pii import PIIFileResult, PIIScanResult


class TestFormatSize:
    """Tests for format_size."""

    def test_zero_bytes(self) -> None:
        assert format_size(0) == "0 B"

    def test_bytes_range(self) -> None:
        assert format_size(1) == "1 B"
        assert format_size(1023) == "1023 B"

    def test_kilobytes_boundary(self) -> None:
        assert format_size(1024) == "1.0 KB"

    def test_kilobytes(self) -> None:
        assert format_size(1536) == "1.5 KB"

    def test_megabytes_boundary(self) -> None:
        assert format_size(1024 * 1024) == "1.0 MB"

    def test_gigabytes_boundary(self) -> None:
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_large_gigabytes(self) -> None:
        assert format_size(5 * 1024 * 1024 * 1024) == "5.0 GB"

    def test_float_input(self) -> None:
        assert format_size(512.0) == "512.0 B"


class TestFormatDuration:
    """Tests for format_duration."""

    def test_zero(self) -> None:
        assert format_duration(0) == "0ms"

    def test_milliseconds(self) -> None:
        assert format_duration(0.001) == "1ms"
        assert format_duration(0.999) == "999ms"

    def test_seconds_boundary(self) -> None:
        assert format_duration(1.0) == "1.0s"

    def test_seconds(self) -> None:
        assert format_duration(30.5) == "30.5s"

    def test_minutes_boundary(self) -> None:
        result = format_duration(60.0)
        assert result == "1m 0s"

    def test_minutes_and_seconds(self) -> None:
        result = format_duration(90.0)
        assert result == "1m 30s"

    def test_large_duration(self) -> None:
        result = format_duration(3661.0)
        assert result == "61m 1s"


class TestTryRelative:
    """Tests for try_relative and try_relative_forward."""

    def test_child_path(self) -> None:
        root = Path("/data/corpus")
        child = Path("/data/corpus/subdir/file.txt")
        assert try_relative(child, root) == str(Path("subdir/file.txt"))

    def test_unrelated_path(self) -> None:
        root = Path("/data/corpus")
        other = Path("/other/path/file.txt")
        result = try_relative(other, root)
        assert result == str(other)

    def test_string_input(self) -> None:
        root = Path("/data/corpus")
        result = try_relative("/data/corpus/file.txt", root)
        assert result == "file.txt"

    def test_forward_slashes(self) -> None:
        root = Path("/data/corpus")
        child = Path("/data/corpus/sub/file.txt")
        result = try_relative_forward(child, root)
        assert "\\" not in result
        assert "sub/file.txt" in result


class TestBuildLookups:
    """Tests for lookup builder functions."""

    def test_duplicate_paths_none(self) -> None:
        assert build_duplicate_paths(None) == set()

    def test_duplicate_paths(self) -> None:
        dedup = DedupResult(
            total_hashed=3,
            unique_files=1,
            duplicate_groups=[
                DuplicateGroup(
                    hash="abc123",
                    size=100,
                    paths=[Path("/a.txt"), Path("/b.txt")],
                )
            ],
            duplicate_file_count=2,
            duplicate_bytes=100,
            duplicate_percentage=66.7,
        )
        paths = build_duplicate_paths(dedup)
        assert str(Path("/a.txt")) in paths
        assert str(Path("/b.txt")) in paths

    def test_hash_lookup_none(self) -> None:
        assert build_hash_lookup(None) == {}

    def test_hash_lookup(self) -> None:
        dedup = DedupResult(
            total_hashed=2,
            unique_files=1,
            duplicate_groups=[
                DuplicateGroup(hash="abc", size=10, paths=[Path("/x"), Path("/y")])
            ],
            duplicate_file_count=2,
            duplicate_bytes=10,
            duplicate_percentage=50.0,
        )
        lookup = build_hash_lookup(dedup)
        assert lookup[str(Path("/x"))] == "abc"
        assert lookup[str(Path("/y"))] == "abc"

    def test_health_lookup_none(self) -> None:
        assert build_health_lookup(None) == {}

    def test_health_lookup(self) -> None:
        corruption = CorruptionResult(
            flagged_files=[
                FileHealth(
                    path=Path("/bad.pdf"), status="corrupt",
                    mime_type="application/pdf", detail="bad header",
                )
            ],
            corrupt_count=1,
        )
        lookup = build_health_lookup(corruption)
        assert lookup[str(Path("/bad.pdf"))] == "corrupt"

    def test_corruption_detail_lookup_none(self) -> None:
        assert build_corruption_detail_lookup(None) == {}

    def test_corruption_detail_lookup(self) -> None:
        corruption = CorruptionResult(
            flagged_files=[
                FileHealth(
                    path=Path("/bad.pdf"), status="truncated",
                    mime_type="application/pdf", detail="missing EOF",
                )
            ],
            corrupt_count=0,
            truncated_count=1,
        )
        lookup = build_corruption_detail_lookup(corruption)
        status, detail = lookup[str(Path("/bad.pdf"))]
        assert status == "truncated"
        assert detail == "missing EOF"

    def test_pii_lookup_none(self) -> None:
        assert build_pii_lookup(None) == {}

    def test_pii_lookup(self) -> None:
        pii = PIIScanResult(
            file_results=[
                PIIFileResult(path="/doc.txt", matches_by_type={"email": 3, "ssn": 1}),
                PIIFileResult(path="/clean.txt", matches_by_type={}),
            ]
        )
        lookup = build_pii_lookup(pii)
        assert "/doc.txt" in lookup
        assert "email" in lookup["/doc.txt"]
        assert "/clean.txt" not in lookup  # No matches

    def test_language_lookup_none(self) -> None:
        assert build_language_lookup(None) == {}

    def test_language_lookup(self) -> None:
        lang = LanguageResult(
            total_analyzed=1,
            language_distribution={"English": 1},
            file_results=[
                LanguageFileResult(path="/en.txt", language="English", script="Latin")
            ],
        )
        lookup = build_language_lookup(lang)
        assert lookup["/en.txt"] == "English"

    def test_encoding_lookup_none(self) -> None:
        assert build_encoding_lookup(None) == {}

    def test_encoding_lookup(self) -> None:
        enc = EncodingResult(
            total_analyzed=1,
            encoding_distribution={"utf-8": 1},
            file_results=[
                EncodingFileResult(path="/f.txt", encoding="utf-8", confidence=0.99)
            ],
        )
        lookup = build_encoding_lookup(enc)
        assert lookup["/f.txt"] == "utf-8"
