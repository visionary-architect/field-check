"""Command-line interface for Field Check."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.console import Console

from field_check import __version__
from field_check.config import load_config
from field_check.report import determine_exit_code, generate_report
from field_check.scanner import walk_directory
from field_check.scanner.corruption import check_corruption
from field_check.scanner.dedup import compute_hashes
from field_check.scanner.encoding import analyze_encodings
from field_check.scanner.inventory import analyze_inventory
from field_check.scanner.language import analyze_languages
from field_check.scanner.mojibake import detect_mojibake
from field_check.scanner.pii import scan_pii
from field_check.scanner.readability import analyze_readability
from field_check.scanner.sampling import estimate_design_effect, select_sample
from field_check.scanner.simhash import detect_near_duplicates
from field_check.scanner.text import extract_text_unified

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="field-check")
def main() -> None:
    """Field Check — Document corpus health scanner."""


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--config", "config_path", type=click.Path(), default=None,
    help="Path to .field-check.yaml config file.",
)
@click.option(
    "--exclude", multiple=True,
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
    "--output", "-o", type=click.Path(), default=None,
    help="Output file path (for non-terminal formats).",
)
@click.option(
    "--sampling-rate", type=float, default=None,
    help="Sampling rate for content analysis (0.0-1.0, default: 0.10).",
)
@click.option(
    "--show-pii-samples", is_flag=True, default=False,
    help="Show matched PII content in report (WARNING: exposes sensitive data).",
)
@click.option(
    "--pii-min-confidence", type=float, default=None,
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

    scan_start = time.monotonic()

    # Walk directory with progress
    with console.status("[bold blue]Scanning files...", spinner="dots") as status:
        def on_progress(count: int) -> None:
            status.update(
                f"[bold blue]Scanning files... [cyan]{count}[/cyan] found"
            )

        try:
            result = walk_directory(
                scan_path, config, progress_callback=on_progress
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Scan interrupted.[/yellow]")
            sys.exit(2)

    if not result.files:
        console.print("[yellow]No files found in the specified directory.[/yellow]")
        console.print("Check your path and exclude patterns.")
        sys.exit(0)

    # Analyze file inventory with progress
    with console.status(
        "[bold blue]Analyzing file types...", spinner="dots"
    ) as status:
        def on_analysis(current: int, total: int) -> None:
            status.update(
                f"[bold blue]Analyzing file types... "
                f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
            )

        inventory = analyze_inventory(result, progress_callback=on_analysis)

    # Hash files for duplicate detection
    with console.status(
        "[bold blue]Hashing files...", spinner="dots"
    ) as status:
        def on_hash(current: int, total: int) -> None:
            status.update(
                f"[bold blue]Hashing files... "
                f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
            )

        dedup_result = compute_hashes(result, progress_callback=on_hash)

    # Check file health (corruption, encryption, emptiness)
    with console.status(
        "[bold blue]Checking file health...", spinner="dots"
    ) as status:
        def on_check(current: int, total: int) -> None:
            status.update(
                f"[bold blue]Checking file health... "
                f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
            )

        corruption_result = check_corruption(
            result, progress_callback=on_check, file_types=inventory.file_types,
        )

    # Override sampling rate from CLI if provided
    if sampling_rate is not None:
        config.sampling_rate = max(0.0, min(1.0, sampling_rate))

    # Override PII min confidence from CLI if provided
    if pii_min_confidence is not None:
        config.pii_min_confidence = max(0.0, min(1.0, pii_min_confidence))

    # Select sample for content analysis
    with console.status("[bold blue]Selecting sample...", spinner="dots"):
        sample = select_sample(result, inventory, config)
        if not sample.is_census:
            sample.deff = estimate_design_effect(sample.selected_files, inventory)

    # Unified text extraction: metadata + classification + text cache in one pass
    text_result = None
    text_cache_result = None
    if sample.total_sample_size > 0:
        with console.status(
            "[bold blue]Extracting text...", spinner="dots"
        ) as status:
            def on_extract(current: int, total: int) -> None:
                status.update(
                    f"[bold blue]Extracting text... "
                    f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
                )

            text_result, text_cache_result = extract_text_unified(
                sample, inventory, progress_callback=on_extract
            )

    # Set show_pii_samples on config
    if show_pii_samples:
        config.show_pii_samples = True

    # Scan for PII patterns (using text cache to avoid re-reading)
    pii_result = None
    if sample.total_sample_size > 0:
        with console.status(
            "[bold blue]Scanning for PII...", spinner="dots"
        ) as status:
            def on_pii(current: int, total: int) -> None:
                status.update(
                    f"[bold blue]Scanning for PII... "
                    f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
                )

            pii_result = scan_pii(
                sample, inventory, config,
                text_cache=(
                    text_cache_result.text_cache if text_cache_result else None
                ),
                progress_callback=on_pii,
            )

    # Detect languages from cached text
    language_result = None
    if text_cache_result and text_cache_result.text_cache:
        with console.status(
            "[bold blue]Detecting languages...", spinner="dots"
        ):
            language_result = analyze_languages(
                text_cache_result.text_cache
            )

    # Analyze encodings from cached detection results
    encoding_result = None
    if text_cache_result and text_cache_result.encoding_map:
        encoding_result = analyze_encodings(text_cache_result.encoding_map)

    # Detect encoding damage (mojibake) in cached text
    mojibake_result = None
    if text_cache_result and text_cache_result.text_cache:
        with console.status(
            "[bold blue]Checking for encoding damage...", spinner="dots"
        ):
            mojibake_result = detect_mojibake(text_cache_result.text_cache)

    # Analyze readability (optional — requires textstat)
    readability_result = None
    if text_cache_result and text_cache_result.text_cache:
        with console.status(
            "[bold blue]Analyzing readability...", spinner="dots"
        ):
            readability_result = analyze_readability(text_cache_result.text_cache)

    # Detect near-duplicates via SimHash
    simhash_result = None
    if text_cache_result and text_cache_result.text_cache:
        with console.status(
            "[bold blue]Detecting near-duplicates...", spinner="dots"
        ) as status:
            def on_simhash(current: int, total: int) -> None:
                status.update(
                    f"[bold blue]Detecting near-duplicates... "
                    f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
                )

            simhash_result = detect_near_duplicates(
                text_cache_result.text_cache,
                threshold=config.simhash_threshold,
                progress_callback=on_simhash,
            )

    elapsed = time.monotonic() - scan_start

    # Generate report
    output_path = Path(output) if output else None
    try:
        generate_report(
            output_format, inventory, result, elapsed, output_path, console,
            dedup_result=dedup_result,
            corruption_result=corruption_result,
            sample_result=sample,
            text_result=text_result,
            pii_result=pii_result,
            language_result=language_result,
            encoding_result=encoding_result,
            simhash_result=simhash_result,
            mojibake_result=mojibake_result,
            readability_result=readability_result,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    # Determine CI exit code based on thresholds
    exit_code, breaches = determine_exit_code(
        config,
        inventory,
        dedup_result=dedup_result,
        corruption_result=corruption_result,
        pii_result=pii_result,
    )
    if exit_code != 0:
        for breach in breaches:
            console.print(f"[red]CRITICAL:[/red] {breach}")
        sys.exit(exit_code)
