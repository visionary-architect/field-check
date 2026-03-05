"""Report generation modules."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from field_check.report.terminal import render_terminal_report
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.sampling import SampleResult
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

    Raises:
        ValueError: If format is not yet supported.
    """
    if fmt == "terminal":
        render_terminal_report(
            inventory, walk_result, elapsed_seconds, console,
            dedup_result=dedup_result,
            corruption_result=corruption_result,
            sample_result=sample_result,
            text_result=text_result,
            pii_result=pii_result,
        )
    else:
        raise ValueError(
            f"Format '{fmt}' not yet supported. Available: terminal"
        )
