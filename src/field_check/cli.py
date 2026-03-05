"""Command-line interface for Field Check."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.console import Console

from field_check import __version__
from field_check.config import load_config
from field_check.report import generate_report
from field_check.scanner import walk_directory
from field_check.scanner.corruption import check_corruption
from field_check.scanner.dedup import compute_hashes
from field_check.scanner.inventory import analyze_inventory

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
    type=click.Choice(["terminal", "html", "json", "csv"], case_sensitive=False),
    default="terminal",
    help="Report output format.",
)
@click.option(
    "--output", "-o", type=click.Path(), default=None,
    help="Output file path (for non-terminal formats).",
)
def scan(
    path: str,
    config_path: str | None,
    exclude: tuple[str, ...],
    output_format: str,
    output: str | None,
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

        corruption_result = check_corruption(result, progress_callback=on_check)

    elapsed = time.monotonic() - scan_start

    # Generate report
    output_path = Path(output) if output else None
    try:
        generate_report(
            output_format, inventory, result, elapsed, output_path, console,
            dedup_result=dedup_result,
            corruption_result=corruption_result,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
