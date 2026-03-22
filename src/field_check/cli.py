"""Command-line interface for Field Check."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from field_check import __version__
from field_check.config import load_config
from field_check.pipeline import PHASES, PipelineResult, run_pipeline
from field_check.report import determine_exit_code, generate_report

console = Console()


def _run_scan_pipeline(
    scan_path: Path,
    config: object,
    con: Console,
) -> PipelineResult:
    """Run the full scan pipeline with Rich progress display.

    Returns PipelineResult with all scan results.
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[cyan]{task.fields[detail]}"),
        TimeElapsedColumn(),
        console=con,
        transient=True,
    ) as progress:
        overall = progress.add_task("Scanning corpus", total=len(PHASES), detail="")

        def on_phase(name: str, index: int, total: int) -> None:
            progress.update(overall, completed=index, description=name, detail="")

        def on_progress(phase: str, current: int, total: int) -> None:
            if total > 0:
                progress.update(overall, detail=f"{current}/{total}")
            else:
                progress.update(overall, detail=f"{current} files found")

        result = run_pipeline(scan_path, config, on_phase=on_phase, on_progress=on_progress)
        progress.update(overall, completed=len(PHASES), detail="done")

    return result


@click.group()
@click.version_option(version=__version__, prog_name="field-check")
def main() -> None:
    """Field Check — Document corpus health scanner."""


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default=None,
    help="Path to .field-check.yaml config file.",
)
@click.option(
    "--exclude",
    multiple=True,
    help="Additional exclude patterns (can be repeated).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["terminal", "html", "json", "csv", "sarif", "junit"], case_sensitive=False),
    default="terminal",
    help="Report output format.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output file path (for non-terminal formats).",
)
@click.option(
    "--sampling-rate",
    type=float,
    default=None,
    help="Sampling rate for content analysis (0.0-1.0). "
    "Auto-tuned by default based on corpus size.",
)
@click.option(
    "--show-pii-samples",
    is_flag=True,
    default=False,
    help="Show matched PII content in report (WARNING: exposes sensitive data).",
)
@click.option(
    "--pii-min-confidence",
    type=float,
    default=None,
    help="Minimum confidence for PII matches (0.0-1.0, default: 0.0).",
)
def scan(
    path: str,
    config_path: str | None,
    exclude: tuple[str, ...],
    output_format: str,
    output: str | None,
    sampling_rate: float | None,
    show_pii_samples: bool,
    pii_min_confidence: float | None,
) -> None:
    """Scan a document corpus and generate a health report."""
    scan_path = Path(path).resolve()

    if not scan_path.is_dir():
        console.print(f"[red]Error:[/red] {scan_path} is not a directory.")
        sys.exit(2)

    # Load config
    cfg_path = Path(config_path) if config_path else None
    config = load_config(scan_path, cfg_path)

    # Merge CLI --exclude patterns
    if exclude:
        config.exclude = list(config.exclude) + list(exclude)

    # Validate output path writability before running the scan
    if output:
        output_dir = Path(output).parent.resolve()
        if not output_dir.exists():
            console.print(f"[red]Error:[/red] Output directory does not exist: {output_dir}")
            sys.exit(2)
        if not os.access(str(output_dir), os.W_OK):
            console.print(f"[red]Error:[/red] Output directory is not writable: {output_dir}")
            sys.exit(2)

    scan_start = time.monotonic()

    # Override sampling rate from CLI if provided
    if sampling_rate is not None:
        config.sampling_rate = max(0.0, min(1.0, sampling_rate))
        config.sampling_rate_auto = False

    # Override PII min confidence from CLI if provided
    if pii_min_confidence is not None:
        config.pii_min_confidence = max(0.0, min(1.0, pii_min_confidence))

    # Set show_pii_samples on config
    if show_pii_samples:
        config.show_pii_samples = True

    # Run pipeline with overall progress tracking
    try:
        pipeline_result = _run_scan_pipeline(scan_path, config, console)
    except KeyboardInterrupt:
        console.print("\n[yellow]Scan interrupted.[/yellow]")
        sys.exit(2)

    if pipeline_result.empty:
        console.print("[yellow]No files found in the specified directory.[/yellow]")
        console.print("Check your path and exclude patterns.")
        sys.exit(0)

    elapsed = time.monotonic() - scan_start

    # Generate report
    output_path = Path(output) if output else None
    try:
        generate_report(
            output_format,
            pipeline_result.inventory,
            pipeline_result.walk,
            elapsed,
            output_path,
            console,
            dedup_result=pipeline_result.dedup,
            corruption_result=pipeline_result.corruption,
            sample_result=pipeline_result.sample,
            text_result=pipeline_result.text,
            pii_result=pipeline_result.pii,
            language_result=pipeline_result.language,
            encoding_result=pipeline_result.encoding,
            simhash_result=pipeline_result.simhash,
            mojibake_result=pipeline_result.mojibake,
            readability_result=pipeline_result.readability,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    # Determine CI exit code based on thresholds
    exit_code, breaches = determine_exit_code(
        config,
        pipeline_result.inventory,
        dedup_result=pipeline_result.dedup,
        corruption_result=pipeline_result.corruption,
        pii_result=pipeline_result.pii,
    )
    if exit_code != 0:
        for breach in breaches:
            console.print(f"[red]CRITICAL:[/red] {breach}")
        sys.exit(exit_code)
