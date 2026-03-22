"""Rich terminal report renderer."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.markup import escape as _esc
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from field_check import __version__
from field_check.report.terminal_content import (
    render_language_encoding,
    render_mojibake_results,
    render_near_duplicates,
    render_pii_results,
    render_readability_results,
    render_text_analysis,
)
from field_check.report.utils import format_duration, format_size
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


def _bar(fraction: float, width: int = 20) -> str:
    """Create a simple bar chart string."""
    filled = int(fraction * width)
    return "#" * filled + "-" * (width - filled)


def render_terminal_report(
    inventory: InventoryResult,
    walk_result: WalkResult,
    elapsed_seconds: float,
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
    """Render a complete terminal report using Rich.

    Args:
        inventory: Analysis results from analyze_inventory().
        walk_result: Raw walk results.
        elapsed_seconds: Total scan duration.
        console: Rich console for output.
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
    """
    # Header
    header_lines = [
        f"[bold]Scan path:[/bold]  {_esc(str(walk_result.scan_root))}",
        f"[bold]Scan date:[/bold]  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"[bold]Duration:[/bold]   {format_duration(elapsed_seconds)}",
        f"[bold]Files:[/bold]      {inventory.total_files:,}",
        f"[bold]Total size:[/bold] {format_size(inventory.total_size)}",
        f"[bold]Directories:[/bold] {inventory.dir_structure.total_dirs:,}",
    ]
    console.print(
        Panel(
            "\n".join(header_lines),
            title="[bold blue]Field Check -- Document Corpus Health Report[/bold blue]",
            border_style="blue",
        )
    )

    # Section 1: File Type Distribution
    _render_type_distribution(inventory, console)

    # Section 2: Duplicate Detection
    if dedup_result is not None:
        _render_dedup_summary(dedup_result, console)

    # Section 3: File Health (Corruption)
    if corruption_result is not None:
        _render_corruption_summary(corruption_result, walk_result, console)

    # Section 4: Document Content Analysis
    if text_result is not None and sample_result is not None:
        render_text_analysis(text_result, sample_result, console)

    # Section 5: PII Risk Indicators
    if pii_result is not None and sample_result is not None:
        render_pii_results(pii_result, sample_result, console)

    # Section 6: Language & Encoding
    if language_result is not None or encoding_result is not None:
        render_language_encoding(language_result, encoding_result, sample_result, console)

    # Section 7: Encoding Damage (Mojibake)
    if mojibake_result is not None:
        render_mojibake_results(mojibake_result, console)

    # Section 7b: Readability Analysis
    if readability_result is not None:
        render_readability_results(readability_result, console)

    # Section 8: Near-Duplicate Detection
    if simhash_result is not None and sample_result is not None:
        render_near_duplicates(simhash_result, sample_result, walk_result, console)

    # Section 8: Size Distribution
    _render_size_distribution(inventory, console)

    # Section 9: File Age Distribution
    _render_age_distribution(inventory, console)

    # Section 10: Directory Structure
    _render_dir_structure(inventory, console)

    # Section 11: Issues
    _render_issues(inventory, dedup_result, text_result, pii_result, console)

    # Footer
    console.print(
        Text(
            f"\nField Check v{__version__} -- All processing local. No data transmitted.",
            style="dim",
        )
    )


def _render_type_distribution(inventory: InventoryResult, console: Console) -> None:
    """Render file type distribution table."""
    if not inventory.type_counts:
        return

    table = Table(title="File Type Distribution", show_lines=False)
    table.add_column("Type", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")
    table.add_column("Total Size", justify="right")
    table.add_column("Avg Size", justify="right")

    sorted_types = sorted(inventory.type_counts.items(), key=lambda x: x[1], reverse=True)

    max_display = 15
    displayed = sorted_types[:max_display]
    remaining = sorted_types[max_display:]

    for mime, count in displayed:
        pct = (count / inventory.total_files * 100) if inventory.total_files else 0
        total_size = inventory.type_sizes.get(mime, 0)
        avg_size = total_size // count if count else 0
        table.add_row(
            mime,
            f"{count:,}",
            f"{pct:.1f}%",
            format_size(total_size),
            format_size(avg_size),
        )

    if remaining:
        other_count = sum(c for _, c in remaining)
        other_size = sum(inventory.type_sizes.get(m, 0) for m, _ in remaining)
        pct = (other_count / inventory.total_files * 100) if inventory.total_files else 0
        avg = other_size // other_count if other_count else 0
        table.add_row(
            f"[dim]Other ({len(remaining)} types)[/dim]",
            f"{other_count:,}",
            f"{pct:.1f}%",
            format_size(other_size),
            format_size(avg),
        )

    console.print(table)
    console.print()


def _render_size_distribution(inventory: InventoryResult, console: Console) -> None:
    """Render size distribution table with bar chart."""
    sd = inventory.size_distribution
    if not sd.buckets:
        return

    table = Table(title="Size Distribution", show_lines=False)
    table.add_column("Range", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")
    table.add_column("Distribution")

    total = inventory.total_files or 1
    for bucket in sd.buckets:
        pct = bucket.count / total * 100
        fraction = bucket.count / total
        table.add_row(
            bucket.label,
            f"{bucket.count:,}",
            f"{pct:.1f}%",
            _bar(fraction),
        )

    console.print(table)

    if inventory.total_files:
        stats = (
            f"  Min: {format_size(sd.min_size)}  "
            f"Max: {format_size(sd.max_size)}  "
            f"Median: {format_size(sd.median_size)}  "
            f"Mean: {format_size(sd.mean_size)}"
        )
        console.print(Text(stats, style="dim"))
    console.print()


def _render_age_distribution(inventory: InventoryResult, console: Console) -> None:
    """Render file age distribution table."""
    ad = inventory.age_distribution
    if not ad.buckets:
        return

    table = Table(title="File Age Distribution", show_lines=False)
    table.add_column("Age Range", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")

    total = inventory.total_files or 1
    for bucket in ad.buckets:
        pct = bucket.count / total * 100
        table.add_row(bucket.label, f"{bucket.count:,}", f"{pct:.1f}%")

    console.print(table)

    if ad.oldest and ad.newest:
        console.print(
            Text(
                f"  Oldest: {ad.oldest.strftime('%Y-%m-%d')}  "
                f"Newest: {ad.newest.strftime('%Y-%m-%d')}",
                style="dim",
            )
        )
    console.print()


def _render_dir_structure(inventory: InventoryResult, console: Console) -> None:
    """Render directory structure metrics."""
    ds = inventory.dir_structure
    table = Table(title="Directory Structure", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Total directories", f"{ds.total_dirs:,}")
    table.add_row("Max depth", str(ds.max_depth))
    table.add_row("Avg depth", f"{ds.avg_depth:.1f}")
    table.add_row("Max files in one dir", f"{ds.max_breadth:,}")
    table.add_row("Avg files per dir", f"{ds.avg_breadth:.1f}")
    if ds.empty_dirs:
        table.add_row("Empty directories", f"{ds.empty_dirs:,}")

    console.print(table)
    console.print()


def _render_issues(
    inventory: InventoryResult,
    dedup_result: DedupResult | None,
    text_result: TextExtractionResult | None,
    pii_result: PIIScanResult | None,
    console: Console,
) -> None:
    """Render issues section if any problems were found."""
    issues: list[tuple[str, int, str]] = []

    if inventory.permission_errors:
        issues.append(("Permission errors", inventory.permission_errors, "yellow"))
    if inventory.symlink_loops:
        issues.append(("Symlink loops", inventory.symlink_loops, "yellow"))
    if inventory.type_detection_errors:
        issues.append(("Type detection errors", inventory.type_detection_errors, "yellow"))
    if dedup_result is not None and dedup_result.hash_errors:
        issues.append(("Hash errors", dedup_result.hash_errors, "yellow"))
    if text_result is not None and text_result.extraction_errors:
        issues.append(("Extraction errors", text_result.extraction_errors, "yellow"))
    if text_result is not None and text_result.timeout_errors:
        issues.append(("Extraction timeouts", text_result.timeout_errors, "yellow"))
    if pii_result is not None and pii_result.scan_errors:
        issues.append(("PII scan errors", pii_result.scan_errors, "yellow"))

    if not issues:
        return

    table = Table(title="Issues", show_lines=False)
    table.add_column("Issue", style="yellow")
    table.add_column("Count", justify="right")

    for label, count, _ in issues:
        table.add_row(label, f"{count:,}")

    console.print(table)
    console.print()


def _render_dedup_summary(dedup: DedupResult, console: Console) -> None:
    """Render duplicate detection summary and detail table."""
    table = Table(title="Duplicate Detection", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Files hashed", f"{dedup.total_hashed:,}")
    table.add_row("Unique files", f"{dedup.unique_files:,}")
    table.add_row("Duplicate groups", f"{len(dedup.duplicate_groups):,}")
    table.add_row("Duplicate files", f"{dedup.duplicate_file_count:,}")
    table.add_row("Wasted space", format_size(dedup.duplicate_bytes))
    table.add_row("Duplicate %", f"{dedup.duplicate_percentage:.1f}%")

    console.print(table)

    # Detail table: top 10 groups by wasted bytes
    if dedup.duplicate_groups:
        sorted_groups = sorted(
            dedup.duplicate_groups,
            key=lambda g: g.size * (len(g.paths) - 1),
            reverse=True,
        )
        top_groups = sorted_groups[:10]

        detail = Table(title="Top Duplicate Groups", show_lines=False)
        detail.add_column("Hash", style="dim")
        detail.add_column("File Size", justify="right")
        detail.add_column("Copies", justify="right")
        detail.add_column("Wasted", justify="right", style="red")
        detail.add_column("Paths")

        for group in top_groups:
            wasted = group.size * (len(group.paths) - 1)
            shown_paths = [str(p) for p in group.paths[:3]]
            path_str = "\n".join(shown_paths)
            if len(group.paths) > 3:
                path_str += f"\n[dim]... and {len(group.paths) - 3} more[/dim]"

            detail.add_row(
                group.hash[:12],
                format_size(group.size),
                str(len(group.paths)),
                format_size(wasted),
                path_str,
            )

        console.print(detail)

    console.print()


def _render_corruption_summary(
    corruption: CorruptionResult,
    walk_result: WalkResult,
    console: Console,
) -> None:
    """Render file health summary and flagged file details."""
    table = Table(title="File Health", show_lines=False)
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right")

    table.add_row("OK", f"{corruption.ok_count:,}")
    if corruption.empty_count:
        table.add_row("[dim]Empty (0 bytes)[/dim]", f"{corruption.empty_count:,}")
    if corruption.near_empty_count:
        table.add_row("[dim]Near-empty (<50 B)[/dim]", f"{corruption.near_empty_count:,}")
    if corruption.corrupt_count:
        table.add_row("[red]Corrupt[/red]", f"{corruption.corrupt_count:,}")
    if corruption.truncated_count:
        table.add_row("[red]Truncated[/red]", f"{corruption.truncated_count:,}")
    if corruption.encrypted_count:
        table.add_row("[yellow]Encrypted[/yellow]", f"{corruption.encrypted_count:,}")
    if corruption.unreadable_count:
        table.add_row("[yellow]Unreadable[/yellow]", f"{corruption.unreadable_count:,}")

    console.print(table)

    # Detail table for flagged files (top 20)
    if corruption.flagged_files:
        flagged = corruption.flagged_files[:20]

        detail = Table(title="Flagged Files", show_lines=False)
        detail.add_column("Path")
        detail.add_column("Status")
        detail.add_column("MIME Type", style="dim")
        detail.add_column("Detail")

        status_styles = {
            "empty": "dim",
            "near_empty": "dim",
            "corrupt": "red",
            "truncated": "red",
            "encrypted_pdf": "yellow",
            "encrypted_zip": "yellow",
            "encrypted_office": "yellow",
            "unreadable": "yellow",
        }

        for fh in flagged:
            try:
                rel = fh.path.relative_to(walk_result.scan_root)
            except ValueError:
                rel = fh.path
            style = status_styles.get(fh.status, "")
            detail.add_row(
                str(rel),
                f"[{style}]{fh.status}[/{style}]" if style else fh.status,
                fh.mime_type or "-",
                fh.detail,
            )

        console.print(detail)
        if len(corruption.flagged_files) > 20:
            console.print(
                Text(
                    f"  ... and {len(corruption.flagged_files) - 20} more flagged files",
                    style="dim",
                )
            )

    console.print()
