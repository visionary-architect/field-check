"""Tests for JUnit XML report output."""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import fromstring

from field_check.report.junit_report import render_junit_report
from field_check.scanner import FileEntry, WalkResult
from field_check.scanner.corruption import CorruptionResult, FileHealth
from field_check.scanner.dedup import DedupResult, DuplicateGroup
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.pii import PIIFileResult, PIIScanResult


def _fe(root: Path, name: str, size: int = 1000) -> FileEntry:
    """Create a minimal FileEntry."""
    return FileEntry(
        path=root / name,
        relative_path=Path(name),
        size=size,
        mtime=0.0,
        ctime=0.0,
        is_symlink=False,
    )


def _make_walk(root: Path, files: list[FileEntry] | None = None) -> WalkResult:
    """Create minimal WalkResult."""
    return WalkResult(scan_root=root, files=files or [])


def _make_inventory(total: int = 0) -> InventoryResult:
    """Create minimal InventoryResult."""
    inv = InventoryResult()
    inv.total_files = total
    return inv


class TestJUnitStructure:
    """Tests for JUnit XML structure."""

    def test_empty_report(self, tmp_path: Path) -> None:
        """Empty report has valid JUnit XML structure."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        output = render_junit_report(inv, walk)
        root = fromstring(output)

        assert root.tag == "testsuite"
        assert root.get("name") == "field-check"
        assert root.get("tests") == "0"
        assert root.get("failures") == "0"
        assert root.get("errors") == "0"

    def test_clean_files_pass(self, tmp_path: Path) -> None:
        """Files without findings are passing test cases."""
        files = [_fe(tmp_path, "good.pdf")]
        walk = _make_walk(tmp_path, files)
        inv = _make_inventory(1)
        output = render_junit_report(inv, walk)
        root = fromstring(output)

        cases = root.findall("testcase")
        assert len(cases) == 1
        assert cases[0].get("name") == "good.pdf"
        assert cases[0].find("failure") is None
        assert cases[0].find("error") is None

    def test_corrupt_file_is_error(self, tmp_path: Path) -> None:
        """Corrupt files produce error elements."""
        files = [_fe(tmp_path, "bad.pdf", 100)]
        walk = _make_walk(tmp_path, files)
        inv = _make_inventory(1)
        corruption = CorruptionResult(
            total_checked=1,
            corrupt_count=1,
            flagged_files=[
                FileHealth(
                    path=tmp_path / "bad.pdf",
                    status="corrupt",
                    mime_type="application/pdf",
                    detail="Header mismatch",
                ),
            ],
        )
        output = render_junit_report(inv, walk, corruption_result=corruption)
        root = fromstring(output)

        cases = root.findall("testcase")
        assert len(cases) == 1
        error = cases[0].find("error")
        assert error is not None
        assert "corrupt" in error.get("message", "")
        assert root.get("errors") == "1"

    def test_pii_finding_is_failure(self, tmp_path: Path) -> None:
        """PII findings produce failure elements without content."""
        files = [_fe(tmp_path, "data.pdf", 5000)]
        walk = _make_walk(tmp_path, files)
        inv = _make_inventory(1)
        pii = PIIScanResult(
            total_scanned=1,
            files_with_pii=1,
            file_results=[
                PIIFileResult(
                    path=str(tmp_path / "data.pdf"),
                    matches_by_type={"ssn": 2},
                ),
            ],
            per_type_counts={"ssn": 2},
            per_type_file_counts={"ssn": 1},
        )
        output = render_junit_report(inv, walk, pii_result=pii)
        root = fromstring(output)

        cases = root.findall("testcase")
        failure = cases[0].find("failure")
        assert failure is not None
        assert "PII risk" in failure.get("message", "")
        # Invariant 3: no PII content
        assert "123-45" not in failure.get("message", "")

    def test_duplicate_finding(self, tmp_path: Path) -> None:
        """Duplicate files produce failure elements."""
        files = [_fe(tmp_path, "orig.pdf"), _fe(tmp_path, "copy.pdf")]
        walk = _make_walk(tmp_path, files)
        inv = _make_inventory(2)
        dedup = DedupResult(
            total_hashed=2,
            unique_files=1,
            duplicate_groups=[
                DuplicateGroup(
                    hash="abc",
                    size=1000,
                    paths=[tmp_path / "orig.pdf", tmp_path / "copy.pdf"],
                ),
            ],
        )
        output = render_junit_report(inv, walk, dedup_result=dedup)
        root = fromstring(output)

        cases = root.findall("testcase")
        # Both files in a duplicate group should have a failure
        copy_case = next(c for c in cases if c.get("name") == "copy.pdf")
        assert copy_case.find("failure") is not None
        orig_case = next(c for c in cases if c.get("name") == "orig.pdf")
        assert orig_case.find("failure") is not None

    def test_xml_declaration(self, tmp_path: Path) -> None:
        """Output starts with XML declaration."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        output = render_junit_report(inv, walk)
        assert output.startswith('<?xml version="1.0"')

    def test_elapsed_time(self, tmp_path: Path) -> None:
        """Elapsed time is included in testsuite."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        output = render_junit_report(inv, walk, elapsed_seconds=1.234)
        root = fromstring(output)
        assert root.get("time") == "1.234"

    def test_unknown_kwargs_ignored(self, tmp_path: Path) -> None:
        """Extra kwargs are silently ignored."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        output = render_junit_report(inv, walk, some_future_param="value")
        root = fromstring(output)
        assert root.tag == "testsuite"
