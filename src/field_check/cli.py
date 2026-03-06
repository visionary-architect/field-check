"""Command-line interface for Field Check."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

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

# Scan phases for progress display
_PHASES = [
    "Scanning files",
    "Analyzing file types",
    "Hashing files",
    "Checking file health",
    "Selecting sample",
    "Extracting text",
    "Scanning for PII",
    "Detecting languages",
    "Analyzing encodings",
    "Checking for encoding damage",
    "Analyzing readability",
    "Detecting near-duplicates",
]


def _run_scan_pipeline(
    scan_path: Path,
    config: object,
    con: Console,
) -> dict:
    """Run the full scan pipeline with overall progress tracking.

    Returns dict of all scan results keyed by name.
    """
    results: dict = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[cyan]{task.fields[detail]}"),
        TimeElapsedColumn(),
        console=con,
        transient=True,
    ) as progress:
        overall = progress.add_task("Scanning corpus", total=len(_PHASES), detail="")

        def _advance(phase_name: str) -> None:
            progress.update(overall, advance=1, description=phase_name)

        # Phase 1: Walk directory
        progress.update(overall, description="Scanning files", detail="")

        def on_walk(count: int) -> None:
            progress.update(overall, detail=f"{count} files found")

        try:
            walk_result = walk_directory(scan_path, config, progress_callback=on_walk)
        except KeyboardInterrupt:
            con.print("\n[yellow]Scan interrupted.[/yellow]")
            sys.exit(2)

        if not walk_result.files:
            con.print("[yellow]No files found in the specified directory.[/yellow]")
            con.print("Check your path and exclude patterns.")
            sys.exit(0)

        results["walk"] = walk_result
        _advance("Analyzing file types")

        # Phase 2: Inventory
        def on_inventory(current: int, total: int) -> None:
            progress.update(overall, detail=f"{current}/{total}")

        results["inventory"] = analyze_inventory(walk_result, progress_callback=on_inventory)
        _advance("Hashing files")

        # Phase 3: Dedup hashing
        def on_hash(current: int, total: int) -> None:
            progress.update(overall, detail=f"{current}/{total}")

        results["dedup"] = compute_hashes(walk_result, progress_callback=on_hash)
        _advance("Checking file health")

        # Phase 4: Corruption
        def on_corruption(current: int, total: int) -> None:
            progress.update(overall, detail=f"{current}/{total}")

        results["corruption"] = check_corruption(
            walk_result,
            progress_callback=on_corruption,
            file_types=results["inventory"].file_types,
        )
        _advance("Selecting sample")

        # Phase 5: Sampling
        progress.update(overall, detail="")
        sample = select_sample(walk_result, results["inventory"], config)
        if not sample.is_census:
            sample.deff = estimate_design_effect(sample.selected_files, results["inventory"])
        results["sample"] = sample
        _advance("Extracting text")

        # Phase 6: Text extraction
        has_sample = sample.total_sample_size > 0
        if has_sample:

            def on_extract(current: int, total: int) -> None:
                progress.update(overall, detail=f"{current}/{total}")

            text_result, text_cache_result = extract_text_unified(
                sample, results["inventory"], progress_callback=on_extract
            )
            results["text"] = text_result
            results["text_cache"] = text_cache_result
        _advance("Scanning for PII")

        # Phase 7: PII scan
        text_cache_result = results.get("text_cache")
        if has_sample:

            def on_pii(current: int, total: int) -> None:
                progress.update(overall, detail=f"{current}/{total}")

            results["pii"] = scan_pii(
                sample,
                results["inventory"],
                config,
                text_cache=(text_cache_result.text_cache if text_cache_result else None),
                progress_callback=on_pii,
            )
        _advance("Detecting languages")

        # Phase 8: Language detection
        progress.update(overall, detail="")
        if text_cache_result and text_cache_result.text_cache:
            results["language"] = analyze_languages(text_cache_result.text_cache)
        _advance("Analyzing encodings")

        # Phase 9: Encoding analysis
        if text_cache_result and text_cache_result.encoding_map:
            results["encoding"] = analyze_encodings(text_cache_result.encoding_map)
        _advance("Checking for encoding damage")

        # Phase 10: Mojibake
        if text_cache_result and text_cache_result.text_cache:
            results["mojibake"] = detect_mojibake(text_cache_result.text_cache)
        _advance("Analyzing readability")

        # Phase 11: Readability
        if text_cache_result and text_cache_result.text_cache:
            results["readability"] = analyze_readability(text_cache_result.text_cache)
        _advance("Detecting near-duplicates")

        # Phase 12: SimHash
        if text_cache_result and text_cache_result.text_cache:

            def on_simhash(current: int, total: int) -> None:
                progress.update(overall, detail=f"{current}/{total}")

            results["simhash"] = detect_near_duplicates(
                text_cache_result.text_cache,
                threshold=config.simhash_threshold,
                bits=config.simhash_bits,
                progress_callback=on_simhash,
            )
        progress.update(overall, advance=1, detail="done")

    return results


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
    help="Sampling rate for content analysis (0.0-1.0, default: 0.10).",
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

    scan_start = time.monotonic()

    # Override sampling rate from CLI if provided
    if sampling_rate is not None:
        config.sampling_rate = max(0.0, min(1.0, sampling_rate))

    # Override PII min confidence from CLI if provided
    if pii_min_confidence is not None:
        config.pii_min_confidence = max(0.0, min(1.0, pii_min_confidence))

    # Set show_pii_samples on config
    if show_pii_samples:
        config.show_pii_samples = True

    # Run pipeline with overall progress tracking
    scan_results = _run_scan_pipeline(scan_path, config, console)

    elapsed = time.monotonic() - scan_start

    # Unpack results
    result = scan_results["walk"]
    inventory = scan_results["inventory"]
    dedup_result = scan_results["dedup"]
    corruption_result = scan_results["corruption"]
    sample = scan_results["sample"]
    text_result = scan_results.get("text")
    pii_result = scan_results.get("pii")
    language_result = scan_results.get("language")
    encoding_result = scan_results.get("encoding")
    mojibake_result = scan_results.get("mojibake")
    readability_result = scan_results.get("readability")
    simhash_result = scan_results.get("simhash")

    # Generate report
    output_path = Path(output) if output else None
    try:
        generate_report(
            output_format,
            inventory,
            result,
            elapsed,
            output_path,
            console,
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
