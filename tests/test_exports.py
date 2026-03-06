"""Tests for JSON, CSV, HTML export modules and CI exit codes."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from click.testing import CliRunner

from field_check.cli import main
from field_check.config import FieldCheckConfig
from field_check.report import determine_exit_code
from field_check.report.csv_report import render_csv_report
from field_check.report.html import render_html_report
from field_check.report.json_report import render_json_report
from field_check.scanner import FileEntry, WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult, DuplicateGroup
from field_check.scanner.inventory import (
    AgeDistribution,
    DirectoryStructure,
    InventoryResult,
    SizeDistribution,
)
from field_check.scanner.pii import PIIFileResult, PIIScanResult
from field_check.scanner.sampling import SampleResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_entry(
    name: str,
    size: int = 100,
    root: Path | None = None,
) -> FileEntry:
    root = root or Path("/corpus")
    return FileEntry(
        path=root / name,
        relative_path=Path(name),
        size=size,
        mtime=1700000000.0,
        ctime=1700000000.0,
        is_symlink=False,
    )


def _make_results() -> dict:
    """Build minimal result objects for export testing."""
    root = Path("/corpus")
    files = [
        _make_file_entry("doc.txt", 500, root),
        _make_file_entry("report.pdf", 2048, root),
        _make_file_entry("dup1.txt", 300, root),
        _make_file_entry("dup2.txt", 300, root),
    ]

    walk = WalkResult(
        files=files,
        total_size=sum(f.size for f in files),
        total_dirs=1,
        scan_root=root,
    )

    inventory = InventoryResult(
        total_files=len(files),
        total_size=walk.total_size,
        type_counts={"text/plain": 3, "application/pdf": 1},
        type_sizes={"text/plain": 1100, "application/pdf": 2048},
        file_types={f.path: "text/plain" for f in files},
        size_distribution=SizeDistribution(),
        age_distribution=AgeDistribution(),
        dir_structure=DirectoryStructure(total_dirs=1),
    )
    inventory.file_types[files[1].path] = "application/pdf"

    dedup = DedupResult(
        total_hashed=4,
        unique_files=3,
        duplicate_groups=[
            DuplicateGroup(
                hash="aabb",
                size=300,
                paths=[root / "dup1.txt", root / "dup2.txt"],
            ),
        ],
        duplicate_file_count=2,
        duplicate_bytes=300,
        duplicate_percentage=50.0,
    )

    corruption = CorruptionResult(total_checked=4, ok_count=4)

    sample = SampleResult(
        selected_files=files,
        total_sample_size=4,
        total_population_size=4,
        sampling_rate=1.0,
        is_census=True,
    )

    pii = PIIScanResult(
        total_scanned=4,
        files_with_pii=1,
        per_type_counts={"email": 2},
        per_type_file_counts={"email": 1},
        file_results=[
            PIIFileResult(
                path=str(root / "doc.txt"),
                matches_by_type={"email": 2},
            ),
        ],
    )

    return {
        "inventory": inventory,
        "walk_result": walk,
        "elapsed_seconds": 1.5,
        "dedup_result": dedup,
        "corruption_result": corruption,
        "sample_result": sample,
        "pii_result": pii,
    }


# ---------------------------------------------------------------------------
# JSON Report
# ---------------------------------------------------------------------------


class TestJSONReport:
    def test_json_valid(self) -> None:
        r = _make_results()
        output = render_json_report(**r)
        data = json.loads(output)
        assert isinstance(data, dict)

    def test_json_has_summary(self) -> None:
        r = _make_results()
        data = json.loads(render_json_report(**r))
        for key in ("version", "scan_path", "scan_date", "summary"):
            assert key in data, f"Missing key: {key}"

    def test_json_has_files_array(self) -> None:
        r = _make_results()
        data = json.loads(render_json_report(**r))
        assert "files" in data
        assert len(data["files"]) == 4

    def test_json_file_entry_fields(self) -> None:
        r = _make_results()
        data = json.loads(render_json_report(**r))
        entry = data["files"][0]
        for key in ("path", "size", "mime_type", "is_duplicate", "health_status"):
            assert key in entry, f"Missing field: {key}"

    def test_json_no_pii_content(self) -> None:
        """PII matched text must never appear in JSON output (Invariant 3)."""
        r = _make_results()
        output = render_json_report(**r)
        assert "matched_text" not in output
        # Verify no email addresses leak into file-level data
        data = json.loads(output)
        files_json = json.dumps(data.get("files", []))
        assert "@" not in files_json, "Email content leaked into file entries"

    def test_json_dedup_data(self) -> None:
        r = _make_results()
        data = json.loads(render_json_report(**r))
        dupes = data["summary"]["duplicates"]
        assert dupes is not None
        assert dupes["duplicate_files"] == 2

    def test_json_null_optional_sections(self) -> None:
        r = _make_results()
        r["pii_result"] = None
        r["dedup_result"] = None
        data = json.loads(render_json_report(**r))
        assert data["summary"]["pii"] is None
        assert data["summary"]["duplicates"] is None


# ---------------------------------------------------------------------------
# CSV Report
# ---------------------------------------------------------------------------


class TestCSVReport:
    def test_csv_valid(self) -> None:
        r = _make_results()
        output = render_csv_report(**r)
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) > 1

    def test_csv_header_row(self) -> None:
        r = _make_results()
        output = render_csv_report(**r)
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        expected = [
            "path",
            "size",
            "mime_type",
            "blake3",
            "is_duplicate",
            "health_status",
            "has_pii",
            "pii_types",
            "language",
            "encoding",
        ]
        assert header == expected

    def test_csv_row_count(self) -> None:
        r = _make_results()
        output = render_csv_report(**r)
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 5  # 1 header + 4 files

    def test_csv_no_pii_content(self) -> None:
        """CSV must not contain PII matched text (Invariant 3)."""
        r = _make_results()
        output = render_csv_report(**r)
        assert "matched_text" not in output

    def test_csv_duplicate_flag(self) -> None:
        r = _make_results()
        output = render_csv_report(**r)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        dup_flags = {row["path"]: row["is_duplicate"] for row in rows}
        assert dup_flags["dup1.txt"] == "True"
        assert dup_flags["dup2.txt"] == "True"
        assert dup_flags["doc.txt"] == "False"


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------


class TestHTMLReport:
    def test_html_valid(self) -> None:
        r = _make_results()
        output = render_html_report(**r)
        assert "<!DOCTYPE html>" in output

    def test_html_has_sections(self) -> None:
        r = _make_results()
        output = render_html_report(**r)
        for heading in (
            "File Type Distribution",
            "Duplicate Detection",
            "Size Distribution",
        ):
            assert heading in output, f"Missing section: {heading}"

    def test_html_self_contained(self) -> None:
        """No external href/src URLs (self-contained report)."""
        r = _make_results()
        output = render_html_report(**r)
        # Should not contain external resource links
        # (Chart.js source maps may reference URLs in comments, that's ok)
        external = re.findall(
            r'(?:href|src)\s*=\s*["\']https?://',
            output,
        )
        assert len(external) == 0

    def test_html_no_pii_content(self) -> None:
        """HTML must not contain PII matched text (Invariant 3)."""
        r = _make_results()
        output = render_html_report(**r)
        assert "matched_text" not in output

    def test_html_chart_js_present(self) -> None:
        r = _make_results()
        output = render_html_report(**r)
        assert "new Chart(" in output


# ---------------------------------------------------------------------------
# Exit Codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_exit_code_clean(self) -> None:
        cfg = FieldCheckConfig()
        inv = InventoryResult(total_files=100)
        dedup = DedupResult(duplicate_percentage=5.0)
        corruption = CorruptionResult(corrupt_count=0)
        pii = PIIScanResult(total_scanned=100, files_with_pii=1)
        code, breaches = determine_exit_code(cfg, inv, dedup, corruption, pii)
        assert code == 0
        assert breaches == []

    def test_exit_code_pii_critical(self) -> None:
        cfg = FieldCheckConfig()  # pii_critical=0.05
        inv = InventoryResult(total_files=100)
        pii = PIIScanResult(total_scanned=100, files_with_pii=10)  # 10%
        code, breaches = determine_exit_code(cfg, inv, pii_result=pii)
        assert code == 1
        assert len(breaches) == 1
        assert "PII" in breaches[0]

    def test_exit_code_duplicate_critical(self) -> None:
        cfg = FieldCheckConfig()  # duplicate_critical=0.10
        inv = InventoryResult(total_files=100)
        dedup = DedupResult(duplicate_percentage=15.0)  # 15%
        code, breaches = determine_exit_code(cfg, inv, dedup_result=dedup)
        assert code == 1
        assert "Duplicate" in breaches[0]

    def test_exit_code_corrupt_critical(self) -> None:
        cfg = FieldCheckConfig()  # corrupt_critical=0.01
        inv = InventoryResult(total_files=100)
        corruption = CorruptionResult(corrupt_count=2)  # 2%
        code, breaches = determine_exit_code(cfg, inv, corruption_result=corruption)
        assert code == 1
        assert "Corruption" in breaches[0]

    def test_exit_code_custom_thresholds(self) -> None:
        cfg = FieldCheckConfig(pii_critical=0.50)  # raise threshold to 50%
        inv = InventoryResult(total_files=100)
        pii = PIIScanResult(total_scanned=100, files_with_pii=10)  # 10%
        # 10% < 50% threshold → clean
        code, _ = determine_exit_code(cfg, inv, pii_result=pii)
        assert code == 0

    def test_exit_code_no_results(self) -> None:
        cfg = FieldCheckConfig()
        inv = InventoryResult(total_files=100)
        code, _ = determine_exit_code(cfg, inv)
        assert code == 0

    def test_exit_code_multiple_breaches(self) -> None:
        cfg = FieldCheckConfig()
        inv = InventoryResult(total_files=100)
        dedup = DedupResult(duplicate_percentage=15.0)
        corruption = CorruptionResult(corrupt_count=5)
        pii = PIIScanResult(total_scanned=100, files_with_pii=10)
        code, breaches = determine_exit_code(cfg, inv, dedup, corruption, pii)
        assert code == 1
        assert len(breaches) == 3


# ---------------------------------------------------------------------------
# CLI Integration
# ---------------------------------------------------------------------------


class TestCLIExportIntegration:
    def test_cli_json_output(self, tmp_corpus: Path, tmp_path: Path) -> None:
        runner = CliRunner()
        out_file = tmp_path / "out" / "report.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        result = runner.invoke(
            main,
            ["scan", str(tmp_corpus), "--format", "json", "-o", str(out_file)],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "files" in data

    def test_cli_csv_output(self, tmp_corpus: Path, tmp_path: Path) -> None:
        runner = CliRunner()
        out_file = tmp_path / "out" / "report.csv"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        result = runner.invoke(
            main,
            ["scan", str(tmp_corpus), "--format", "csv", "-o", str(out_file)],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        reader = csv.reader(
            io.StringIO(out_file.read_text(encoding="utf-8")),
        )
        rows = list(reader)
        assert rows[0][0] == "path"

    def test_cli_html_output(self, tmp_corpus: Path, tmp_path: Path) -> None:
        runner = CliRunner()
        out_file = tmp_path / "out" / "report.html"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        result = runner.invoke(
            main,
            ["scan", str(tmp_corpus), "--format", "html", "-o", str(out_file)],
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content


# ---------------------------------------------------------------------------
# Config Thresholds
# ---------------------------------------------------------------------------


class TestConfigThresholds:
    def test_default_thresholds(self) -> None:
        cfg = FieldCheckConfig()
        assert cfg.pii_critical == 0.05
        assert cfg.duplicate_critical == 0.10
        assert cfg.corrupt_critical == 0.01

    def test_yaml_thresholds(self, tmp_path: Path) -> None:
        yaml_content = (
            "thresholds:\n"
            "  pii_critical: 0.20\n"
            "  duplicate_critical: 0.30\n"
            "  corrupt_critical: 0.05\n"
        )
        config_file = tmp_path / ".field-check.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")
        from field_check.config import load_config

        cfg = load_config(tmp_path, config_file)
        assert cfg.pii_critical == 0.20
        assert cfg.duplicate_critical == 0.30
        assert cfg.corrupt_critical == 0.05

    def test_yaml_threshold_clamping(self, tmp_path: Path) -> None:
        yaml_content = "thresholds:\n  pii_critical: 5.0\n  corrupt_critical: -0.5\n"
        config_file = tmp_path / ".field-check.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")
        from field_check.config import load_config

        cfg = load_config(tmp_path, config_file)
        assert cfg.pii_critical == 1.0  # clamped to max
        assert cfg.corrupt_critical == 0.0  # clamped to min
