"""Tests for gaps identified during comprehensive code review.

Covers:
- G1: CLI integration test for --format sarif and --format junit
- G2: HTML report XSS safety test (malicious filenames)
- G3: (skipped — multi-worker test requires process pool; covered by CI)
- G4: Pipeline integration test with PDFs/DOCXes
- G5: Unicode file paths
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

from click.testing import CliRunner

from field_check.cli import main
from field_check.report.html import render_html_report
from field_check.scanner import WalkResult
from field_check.scanner.inventory import InventoryResult

# ---------------------------------------------------------------------------
# G1: CLI integration tests for --format sarif and --format junit
# ---------------------------------------------------------------------------


class TestCLISarifJunit:
    """Ensure sarif and junit formats produce valid output via CLI."""

    def test_cli_format_sarif(self, tmp_corpus: Path, tmp_path: Path) -> None:
        output_file = tmp_path / "report.sarif"
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan", "--format", "sarif", "--output", str(output_file), str(tmp_corpus)],
        )
        assert result.exit_code == 0
        content = output_file.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["$schema"].startswith("https://")
        assert data["version"] == "2.1.0"
        assert len(data["runs"]) == 1

    def test_cli_format_junit(self, tmp_corpus: Path, tmp_path: Path) -> None:
        output_file = tmp_path / "report.xml"
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan", "--format", "junit", "--output", str(output_file), str(tmp_corpus)],
        )
        assert result.exit_code == 0
        content = output_file.read_text(encoding="utf-8")
        root = ElementTree.fromstring(content)
        assert root.tag == "testsuite"
        assert root.get("name") == "field-check"
        tests = int(root.get("tests", "0"))
        assert tests > 0


# ---------------------------------------------------------------------------
# G2: HTML report XSS safety with malicious filenames
# ---------------------------------------------------------------------------


class TestHTMLXSSSafety:
    """Verify HTML report escapes user-controlled data."""

    def test_xss_in_scan_path(self) -> None:
        """Scan path containing <script> tags must be escaped."""
        xss_path = '<script>alert("xss")</script>'
        walk = WalkResult(
            scan_root=Path("/tmp"),
            files=[],
            total_dirs=0,
            empty_dirs=0,
            total_size=0,
            permission_errors=[],
            symlink_loops=[],
            excluded_count=0,
        )
        # Monkey-patch scan_root for the test
        walk.scan_root = Path(xss_path)

        inv = InventoryResult(
            total_files=0,
            total_size=0,
            type_counts={},
            type_sizes={},
            extension_counts={},
        )
        html = render_html_report(
            inventory=inv,
            walk_result=walk,
            elapsed_seconds=0.1,
        )
        # The raw script tag must NOT appear — Jinja2 autoescape should encode it
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html or "alert" not in html

    def test_xss_in_file_type(self) -> None:
        """MIME types in type distribution must be escaped."""
        xss_mime = '<img src=x onerror=alert(1)>'
        walk = WalkResult(
            scan_root=Path("/tmp/safe"),
            files=[],
            total_dirs=1,
            empty_dirs=0,
            total_size=100,
            permission_errors=[],
            symlink_loops=[],
            excluded_count=0,
        )
        inv = InventoryResult(
            total_files=1,
            total_size=100,
            type_counts={xss_mime: 1},
            type_sizes={xss_mime: 100},
            extension_counts={".txt": 1},
        )
        html = render_html_report(
            inventory=inv,
            walk_result=walk,
            elapsed_seconds=0.1,
        )
        assert "<img src=x" not in html


# ---------------------------------------------------------------------------
# G4: Pipeline integration test with PDFs/DOCXes
# ---------------------------------------------------------------------------


class TestPipelineWithDocuments:
    """Pipeline with real document types exercises full extraction path."""

    def test_pipeline_with_pdfs_and_docx(self, tmp_corpus_with_documents: Path) -> None:
        from field_check.config import FieldCheckConfig
        from field_check.pipeline import run_pipeline

        config = FieldCheckConfig()
        result = run_pipeline(tmp_corpus_with_documents, config)

        assert not result.empty
        assert result.inventory.total_files >= 6

        # Text extraction ran
        assert result.text is not None
        assert result.text.total_processed > 0

        # Language detection ran
        assert result.language is not None
        assert result.language.total_analyzed > 0

        # Encoding detection ran
        assert result.encoding is not None

        # PII detection ran
        assert result.pii is not None


# ---------------------------------------------------------------------------
# G5: Unicode file paths
# ---------------------------------------------------------------------------


class TestUnicodeFilePaths:
    """Scanner and reports must handle Unicode filenames."""

    def test_unicode_filenames_in_scan(self, tmp_path: Path) -> None:
        """Files with Unicode names are scanned without errors."""
        # Create files with various Unicode names
        (tmp_path / "résumé.txt").write_text(
            "This is a résumé document with enough text.", encoding="utf-8"
        )
        (tmp_path / "日本語.txt").write_text(
            "日本語のテキストファイルです。テスト用の文書。", encoding="utf-8"
        )
        (tmp_path / "données.csv").write_text(
            "nom,âge\nJean,30\nPierre,25\n", encoding="utf-8"
        )

        runner = CliRunner()
        result = runner.invoke(main, ["scan", str(tmp_path)])
        assert result.exit_code == 0
        assert "3" in result.output or "Total files" in result.output

    def test_unicode_filenames_json_output(self, tmp_path: Path) -> None:
        """JSON report handles Unicode paths correctly."""
        (tmp_path / "café.txt").write_text("Coffee shop menu.", encoding="utf-8")
        output_file = tmp_path / "report.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["scan", "--format", "json", "--output", str(output_file), str(tmp_path)],
        )
        assert result.exit_code == 0
        data = json.loads(output_file.read_text(encoding="utf-8"))
        paths = [f["path"] for f in data["files"]]
        assert any("café" in p for p in paths)
