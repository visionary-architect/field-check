"""Tests for SARIF report output."""

from __future__ import annotations

import json
from pathlib import Path

from field_check.report.sarif_report import render_sarif_report
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult, FileHealth
from field_check.scanner.dedup import DedupResult, DuplicateGroup
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.mojibake import MojibakeResult
from field_check.scanner.pii import PIIFileResult, PIIScanResult


def _make_walk(root: Path) -> WalkResult:
    """Create minimal WalkResult."""
    return WalkResult(scan_root=root, files=[])


def _make_inventory() -> InventoryResult:
    """Create minimal InventoryResult."""
    return InventoryResult()


class TestSARIFStructure:
    """Tests for SARIF JSON structure."""

    def test_empty_report_structure(self, tmp_path: Path) -> None:
        """Empty report has valid SARIF structure."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        output = render_sarif_report(inv, walk)
        data = json.loads(output)

        assert data["version"] == "2.1.0"
        assert "$schema" in data
        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert run["tool"]["driver"]["name"] == "field-check"
        assert len(run["tool"]["driver"]["rules"]) > 0
        assert run["results"] == []

    def test_corruption_findings(self, tmp_path: Path) -> None:
        """Corruption findings map to correct SARIF rules."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        corruption = CorruptionResult(
            total_checked=3,
            corrupt_count=1,
            truncated_count=1,
            encrypted_count=1,
            flagged_files=[
                FileHealth(
                    path=tmp_path / "bad.pdf",
                    status="corrupt",
                    mime_type="application/pdf",
                    detail="Header mismatch",
                ),
                FileHealth(
                    path=tmp_path / "trunc.pdf",
                    status="truncated",
                    mime_type="application/pdf",
                    detail="Missing %%EOF",
                ),
                FileHealth(
                    path=tmp_path / "enc.pdf",
                    status="encrypted_pdf",
                    mime_type="application/pdf",
                    detail="PDF contains /Encrypt",
                ),
            ],
        )
        output = render_sarif_report(inv, walk, corruption_result=corruption)
        data = json.loads(output)
        results = data["runs"][0]["results"]

        assert len(results) == 3
        rule_ids = [r["ruleId"] for r in results]
        assert "FC001" in rule_ids  # corrupt
        assert "FC002" in rule_ids  # truncated
        assert "FC003" in rule_ids  # encrypted

    def test_pii_findings_no_content(self, tmp_path: Path) -> None:
        """PII findings include counts but never matched content (Invariant 3)."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        pii = PIIScanResult(
            total_scanned=1,
            files_with_pii=1,
            file_results=[
                PIIFileResult(
                    path=str(tmp_path / "data.pdf"),
                    matches_by_type={"ssn": 3, "email": 2},
                ),
            ],
            per_type_counts={"ssn": 3, "email": 2},
            per_type_file_counts={"ssn": 1, "email": 1},
        )
        output = render_sarif_report(inv, walk, pii_result=pii)
        data = json.loads(output)
        results = data["runs"][0]["results"]

        assert len(results) == 1
        assert results[0]["ruleId"] == "FC005"
        assert results[0]["level"] == "warning"
        # Invariant 3: no PII content in output
        msg = results[0]["message"]["text"]
        assert "5 PII risk indicator(s)" in msg
        # Should NOT contain actual PII values
        assert "123-45-6789" not in msg

    def test_duplicate_findings(self, tmp_path: Path) -> None:
        """Duplicate findings map to FC006."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        dedup = DedupResult(
            total_hashed=3,
            unique_files=1,
            duplicate_groups=[
                DuplicateGroup(
                    hash="abc123",
                    size=1000,
                    paths=[
                        tmp_path / "orig.pdf",
                        tmp_path / "copy1.pdf",
                        tmp_path / "copy2.pdf",
                    ],
                ),
            ],
        )
        output = render_sarif_report(inv, walk, dedup_result=dedup)
        data = json.loads(output)
        results = data["runs"][0]["results"]

        # 2 duplicates (skip the original)
        assert len(results) == 2
        assert all(r["ruleId"] == "FC006" for r in results)
        assert all(r["level"] == "note" for r in results)

    def test_mojibake_findings(self, tmp_path: Path) -> None:
        """Mojibake findings map to FC007."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        mojibake = MojibakeResult(
            total_checked=5,
            files_with_mojibake=2,
            mojibake_files=["file1.txt", "file2.txt"],
        )
        output = render_sarif_report(inv, walk, mojibake_result=mojibake)
        data = json.loads(output)
        results = data["runs"][0]["results"]

        assert len(results) == 2
        assert all(r["ruleId"] == "FC007" for r in results)
        assert all(r["level"] == "note" for r in results)

    def test_locations_have_uri(self, tmp_path: Path) -> None:
        """All results have location URIs."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        corruption = CorruptionResult(
            total_checked=1,
            empty_count=1,
            flagged_files=[
                FileHealth(
                    path=tmp_path / "empty.txt",
                    status="empty",
                    mime_type="text/plain",
                    detail="File is empty",
                ),
            ],
        )
        output = render_sarif_report(inv, walk, corruption_result=corruption)
        data = json.loads(output)
        results = data["runs"][0]["results"]

        assert len(results) == 1
        loc = results[0]["locations"][0]["physicalLocation"]
        assert "artifactLocation" in loc
        assert "uri" in loc["artifactLocation"]

    def test_unknown_kwargs_ignored(self, tmp_path: Path) -> None:
        """Extra kwargs are silently ignored."""
        walk = _make_walk(tmp_path)
        inv = _make_inventory()
        # Should not raise
        output = render_sarif_report(
            inv, walk, some_future_param="value",
        )
        data = json.loads(output)
        assert data["version"] == "2.1.0"
