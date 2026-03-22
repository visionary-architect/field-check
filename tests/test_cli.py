"""Integration tests for the CLI."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from field_check.cli import main


def test_cli_version() -> None:
    """field-check --version prints version."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_scan_basic(tmp_corpus: Path) -> None:
    """field-check scan <path> exits 0."""
    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_corpus)])
    assert result.exit_code == 0


def test_cli_scan_output_contains_sections(tmp_corpus: Path) -> None:
    """Output contains expected report sections."""
    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_corpus)])
    output = result.output
    assert "File Type Distribution" in output
    assert "Size Distribution" in output
    assert "File Age Distribution" in output
    assert "Directory Structure" in output


def test_cli_scan_nonexistent_path() -> None:
    """Exits with error for nonexistent path."""
    runner = CliRunner()
    result = runner.invoke(main, ["scan", "/nonexistent/path/xyz123"])
    assert result.exit_code != 0


def test_cli_scan_with_exclude(tmp_corpus: Path) -> None:
    """--exclude reduces file count in output."""
    runner = CliRunner()
    # Without exclude
    r1 = runner.invoke(main, ["scan", str(tmp_corpus)])
    # With exclude
    r2 = runner.invoke(main, ["scan", "--exclude", "*.bin", str(tmp_corpus)])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    # Output with exclude should show fewer files (or same sections)
    assert "7" in r1.output or "Files" in r1.output
    assert r2.output != r1.output


def test_cli_scan_with_config(tmp_corpus_with_config: Path) -> None:
    """--config loads custom config."""
    runner = CliRunner()
    config_file = tmp_corpus_with_config / ".field-check.yaml"
    result = runner.invoke(
        main, ["scan", "--config", str(config_file), str(tmp_corpus_with_config)]
    )
    assert result.exit_code == 0


def test_cli_scan_unsupported_format(tmp_corpus: Path) -> None:
    """--format with invalid value shows error."""
    runner = CliRunner()
    result = runner.invoke(main, ["scan", "--format", "xml", str(tmp_corpus)])
    assert result.exit_code != 0


def test_cli_scan_file_count_in_output(tmp_corpus: Path) -> None:
    """Report shows correct total file count."""
    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_corpus)])
    # 7 files in tmp_corpus (with default excludes=[.git, etc.] which don't apply)
    assert "7" in result.output


def test_cli_scan_shows_duration(tmp_corpus: Path) -> None:
    """Report output contains scan duration."""
    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_corpus)])
    assert "Duration" in result.output


def test_invariant2_scan_never_modifies_files(tmp_corpus: Path) -> None:
    """INVARIANT 2: Scan must never modify, delete, or create user files.

    Snapshot mtimes and sizes before/after a full scan and assert
    nothing changed.
    """
    import os

    # Snapshot: {relative_path: (size, mtime_ns)}
    before: dict[str, tuple[int, int]] = {}
    for root, _dirs, files in os.walk(tmp_corpus):
        for name in files:
            p = Path(root) / name
            st = p.stat()
            before[str(p.relative_to(tmp_corpus))] = (st.st_size, st.st_mtime_ns)

    runner = CliRunner()
    result = runner.invoke(main, ["scan", str(tmp_corpus)])
    assert result.exit_code == 0

    # Snapshot after
    after: dict[str, tuple[int, int]] = {}
    for root, _dirs, files in os.walk(tmp_corpus):
        for name in files:
            p = Path(root) / name
            st = p.stat()
            after[str(p.relative_to(tmp_corpus))] = (st.st_size, st.st_mtime_ns)

    assert before.keys() == after.keys(), "Files were created or deleted"
    for key in before:
        assert before[key] == after[key], f"File modified: {key}"
