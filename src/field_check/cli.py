"""Command-line interface for Field Check."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from field_check import __version__
from field_check.config import load_config
from field_check.scanner import walk_directory

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
@click.option("--exclude", multiple=True, help="Additional exclude patterns (can be repeated).")
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

    # Walk directory with progress
    with console.status("[bold blue]Scanning files...", spinner="dots") as status:
        def on_progress(count: int) -> None:
            status.update(f"[bold blue]Scanning files... [cyan]{count}[/cyan] found")

        try:
            result = walk_directory(scan_path, config, progress_callback=on_progress)
        except KeyboardInterrupt:
            console.print("\n[yellow]Scan interrupted.[/yellow]")
            sys.exit(2)

    # Summary (temporary — Plan B will replace with full report)
    size_mb = result.total_size / (1024 * 1024)
    console.print(
        f"\nFound [bold]{len(result.files)}[/bold] files "
        f"([cyan]{size_mb:.1f} MB[/cyan]) in [green]{scan_path}[/green]"
    )
    if result.permission_errors:
        console.print(
            f"[yellow]  {len(result.permission_errors)} permission errors[/yellow]"
        )
    if result.symlink_loops:
        console.print(
            f"[yellow]  {len(result.symlink_loops)} symlink loops detected[/yellow]"
        )
    if result.excluded_count:
        console.print(f"  {result.excluded_count} items excluded")
