"""Report generation modules."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from field_check.config import FieldCheckConfig
from field_check.report.csv_report import render_csv_report
from field_check.report.html import render_html_report
from field_check.report.json_report import render_json_report
from field_check.report.sarif_report import render_sarif_report
from field_check.report.terminal import render_terminal_report
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.mojibake import MojibakeResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.readability import ReadabilityResult
from field_check.scanner.sampling import SampleResult
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import TextExtractionResult


def generate_report(
    fmt: str,
    inventory: InventoryResult,
    walk_result: WalkResult,
    elapsed_seconds: float,
    output_path: Path | None,
    console: Console,
    dedup_result: DedupResult | None = None,
    corruption_result: CorruptionResult | None = None,
    sample_result: SampleResult | None = None,
    text_result: TextExtractionResult | None = None,
    pii_result: PIIScanResult | None = None,
    language_result: LanguageResult | None = None,
    encoding_result: EncodingResult | None = None,
    simhash_result: SimHashResult | None = None,
    mojibake_result: MojibakeResult | None = None,
    readability_result: ReadabilityResult | None = None,
) -> None:
    """Generate a report in the specified format.

    Args:
        fmt: Output format ("terminal", "html", "json", "csv").
        inventory: Analysis results.
        walk_result: Raw walk results.
        elapsed_seconds: Total scan duration.
        output_path: File path for non-terminal output.
        console: Rich console for terminal output.
        dedup_result: Duplicate detection results (optional).
        corruption_result: Corruption detection results (optional).
        sample_result: Sampling results (optional).
        text_result: Text extraction results (optional).
        pii_result: PII scan results (optional).
        language_result: Language detection results (optional).
        encoding_result: Encoding detection results (optional).
        simhash_result: Near-duplicate detection results (optional).
        mojibake_result: Mojibake (encoding damage) results (optional).
        readability_result: Readability scoring results (optional).

    Raises:
        ValueError: If format is not yet supported.
    """
    kwargs = {
        "dedup_result": dedup_result,
        "corruption_result": corruption_result,
        "sample_result": sample_result,
        "text_result": text_result,
        "pii_result": pii_result,
        "language_result": language_result,
        "encoding_result": encoding_result,
        "simhash_result": simhash_result,
        "mojibake_result": mojibake_result,
        "readability_result": readability_result,
    }

    if fmt == "terminal":
        render_terminal_report(
            inventory, walk_result, elapsed_seconds, console,
            **kwargs,
        )
    elif fmt == "json":
        content = render_json_report(
            inventory, walk_result, elapsed_seconds, **kwargs,
        )
        path = output_path or Path("field-check-report.json")
        path.write_text(content, encoding="utf-8")
        console.print(f"Report saved to [bold]{path}[/bold]")
    elif fmt == "csv":
        content = render_csv_report(
            inventory, walk_result, elapsed_seconds, **kwargs,
        )
        path = output_path or Path("field-check-report.csv")
        path.write_text(content, encoding="utf-8")
        console.print(f"Report saved to [bold]{path}[/bold]")
    elif fmt == "html":
        content = render_html_report(
            inventory, walk_result, elapsed_seconds, **kwargs,
        )
        path = output_path or Path("field-check-report.html")
        path.write_text(content, encoding="utf-8")
        console.print(f"Report saved to [bold]{path}[/bold]")
    elif fmt == "sarif":
        content = render_sarif_report(
            inventory, walk_result, **kwargs,
        )
        path = output_path or Path("field-check-report.sarif.json")
        path.write_text(content, encoding="utf-8")
        console.print(f"Report saved to [bold]{path}[/bold]")
    else:
        raise ValueError(
            f"Format '{fmt}' not yet supported. "
            "Available: terminal, html, json, csv, sarif"
        )


def determine_exit_code(
    config: FieldCheckConfig,
    inventory: InventoryResult,
    dedup_result: DedupResult | None = None,
    corruption_result: CorruptionResult | None = None,
    pii_result: PIIScanResult | None = None,
) -> tuple[int, list[str]]:
    """Determine CI exit code based on configured thresholds.

    Checks ALL thresholds and returns all breaches so the user
    can see every issue at once instead of fixing one at a time.

    Args:
        config: Configuration with threshold values.
        inventory: Inventory results for total file count.
        dedup_result: Duplicate detection results.
        corruption_result: Corruption detection results.
        pii_result: PII scan results.

    Returns:
        Tuple of (exit_code, list of breach descriptions).
        exit_code is 0 if no breaches, 1 if any threshold exceeded.
    """
    breaches: list[str] = []

    if dedup_result is not None:
        dup_rate = dedup_result.duplicate_percentage / 100.0
        if dup_rate >= config.duplicate_critical:
            breaches.append(
                f"Duplicate rate {dup_rate:.1%} >= "
                f"threshold {config.duplicate_critical:.1%}"
            )

    if corruption_result is not None and inventory.total_files > 0:
        corrupt_rate = corruption_result.corrupt_count / inventory.total_files
        if corrupt_rate >= config.corrupt_critical:
            breaches.append(
                f"Corruption rate {corrupt_rate:.1%} >= "
                f"threshold {config.corrupt_critical:.1%}"
            )

    if pii_result is not None and pii_result.total_scanned > 0:
        pii_rate = pii_result.files_with_pii / pii_result.total_scanned
        if pii_rate >= config.pii_critical:
            breaches.append(
                f"PII rate {pii_rate:.1%} >= "
                f"threshold {config.pii_critical:.1%}"
            )

    return (1 if breaches else 0, breaches)
