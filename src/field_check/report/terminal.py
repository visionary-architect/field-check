"""Rich terminal report renderer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from field_check import __version__
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.sampling import SampleResult, compute_confidence_interval, format_ci
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import METADATA_FIELDS, PAGE_COUNT_BUCKETS, TextExtractionResult


def _format_size(size_bytes: int | float) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _format_duration(seconds: float) -> str:
    """Format elapsed seconds into human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


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
    """
    # Header
    header_lines = [
        f"[bold]Scan path:[/bold]  {walk_result.scan_root}",
        f"[bold]Scan date:[/bold]  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"[bold]Duration:[/bold]   {_format_duration(elapsed_seconds)}",
        f"[bold]Files:[/bold]      {inventory.total_files:,}",
        f"[bold]Total size:[/bold] {_format_size(inventory.total_size)}",
        f"[bold]Directories:[/bold] {inventory.dir_structure.total_dirs:,}",
    ]
    console.print(Panel(
        "\n".join(header_lines),
        title="[bold blue]Field Check -- Document Corpus Health Report[/bold blue]",
        border_style="blue",
    ))

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
        _render_text_analysis(text_result, sample_result, console)

    # Section 5: PII Risk Indicators
    if pii_result is not None and sample_result is not None:
        _render_pii_results(pii_result, sample_result, console)

    # Section 6: Language & Encoding
    if language_result is not None or encoding_result is not None:
        _render_language_encoding(
            language_result, encoding_result, sample_result, console
        )

    # Section 7: Near-Duplicate Detection
    if simhash_result is not None and sample_result is not None:
        _render_near_duplicates(simhash_result, sample_result, walk_result, console)

    # Section 8: Size Distribution
    _render_size_distribution(inventory, console)

    # Section 7: File Age Distribution
    _render_age_distribution(inventory, console)

    # Section 8: Directory Structure
    _render_dir_structure(inventory, console)

    # Section 9: Issues
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

    sorted_types = sorted(
        inventory.type_counts.items(), key=lambda x: x[1], reverse=True
    )

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
            _format_size(total_size),
            _format_size(avg_size),
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
            _format_size(other_size),
            _format_size(avg),
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
            f"  Min: {_format_size(sd.min_size)}  "
            f"Max: {_format_size(sd.max_size)}  "
            f"Median: {_format_size(sd.median_size)}  "
            f"Mean: {_format_size(sd.mean_size)}"
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
        console.print(Text(
            f"  Oldest: {ad.oldest.strftime('%Y-%m-%d')}  "
            f"Newest: {ad.newest.strftime('%Y-%m-%d')}",
            style="dim",
        ))
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
    table.add_row("Wasted space", _format_size(dedup.duplicate_bytes))
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
                _format_size(group.size),
                str(len(group.paths)),
                _format_size(wasted),
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
            "encrypted_pdf": "yellow",
            "encrypted_zip": "yellow",
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
            console.print(Text(
                f"  ... and {len(corruption.flagged_files) - 20} more flagged files",
                style="dim",
            ))

    console.print()


def _render_text_analysis(
    text: TextExtractionResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render document content analysis with confidence intervals."""
    if text.total_processed == 0:
        return

    # Summary
    summary = Table(title="Document Content Analysis", show_lines=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Files analyzed", f"{text.total_processed:,}")
    summary.add_row("Total corpus files", f"{sample.total_population_size:,}")
    rate_pct = sample.sampling_rate * 100
    summary.add_row("Sampling rate", f"{rate_pct:.0f}%")
    if text.extraction_errors:
        summary.add_row("[yellow]Extraction errors[/yellow]", f"{text.extraction_errors:,}")
    console.print(summary)

    # Scanned PDF detection
    _render_scanned_detection(text, sample, console)

    # Content classification
    _render_content_classification(text, sample, console)

    # Metadata completeness
    _render_metadata_completeness(text, sample, console)

    # Page count distribution
    _render_page_count_distribution(text, console)

    console.print()


def _render_scanned_detection(
    text: TextExtractionResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render scanned vs native PDF detection with confidence intervals."""
    total_classified = text.scanned_count + text.native_count + text.mixed_scan_count
    if total_classified == 0:
        return

    pdf_pop = sample.per_type_population.get("application/pdf", total_classified)

    table = Table(title="Scanned PDF Detection", show_lines=False)
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Proportion", justify="right")

    for label, count in [
        ("Native (has text layer)", text.native_count),
        ("Scanned (image-only)", text.scanned_count),
        ("Mixed (partial text)", text.mixed_scan_count),
    ]:
        if count > 0 or label.startswith("Native"):
            ci = compute_confidence_interval(count, total_classified, pdf_pop)
            table.add_row(label, f"{count:,}", format_ci(ci))

    console.print(table)


def _render_content_classification(
    text: TextExtractionResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render text-heavy vs image-heavy classification with CIs."""
    total = text.text_heavy_count + text.image_heavy_count + text.mixed_content_count
    if total == 0:
        return

    pop = text.total_processed - text.extraction_errors
    if pop <= 0:
        pop = total

    table = Table(title="Content Classification", show_lines=False)
    table.add_column("Classification", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Proportion", justify="right")

    for label, count in [
        ("Text-heavy (>500 chars/page)", text.text_heavy_count),
        ("Image-heavy (<100 chars/page)", text.image_heavy_count),
        ("Mixed (100-500 chars/page)", text.mixed_content_count),
    ]:
        if count > 0:
            ci = compute_confidence_interval(count, total, pop)
            table.add_row(label, f"{count:,}", format_ci(ci))

    console.print(table)


def _render_metadata_completeness(
    text: TextExtractionResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render per-field metadata completeness with confidence intervals."""
    if text.metadata_total_checked == 0:
        return

    n = text.metadata_total_checked
    pop = n  # population is the checked files

    table = Table(title="Metadata Completeness", show_lines=False)
    table.add_column("Field", style="cyan")
    table.add_column("Files with value", justify="right")
    table.add_column("Completeness", justify="right")

    for field_name in METADATA_FIELDS:
        count = text.metadata_field_counts.get(field_name, 0)
        ci = compute_confidence_interval(count, n, pop)
        display_name = field_name.replace("_", " ").title()
        table.add_row(display_name, f"{count:,}", format_ci(ci))

    console.print(table)


def _render_page_count_distribution(
    text: TextExtractionResult,
    console: Console,
) -> None:
    """Render page count distribution for documents with pages."""
    if not text.page_count_distribution:
        return

    total_docs_with_pages = sum(text.page_count_distribution.values())

    table = Table(title="Page Count Distribution", show_lines=False)
    table.add_column("Range", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")

    for _, _, label in PAGE_COUNT_BUCKETS:
        count = text.page_count_distribution.get(label, 0)
        if count > 0 or label in ("1 page", "2-5 pages"):
            pct = count / total_docs_with_pages * 100 if total_docs_with_pages else 0
            table.add_row(label, f"{count:,}", f"{pct:.1f}%")

    console.print(table)
    if total_docs_with_pages > 0:
        mean = text.page_count_total / total_docs_with_pages
        console.print(Text(
            f"  Min: {text.page_count_min}  Max: {text.page_count_max}  "
            f"Mean: {mean:.1f}",
            style="dim",
        ))


def _render_pii_results(
    pii: PIIScanResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render PII risk indicators with per-type breakdown."""
    if pii.total_scanned == 0:
        return

    # Warning banner if samples are shown
    if pii.show_pii_samples:
        console.print(Panel(
            "[bold yellow]WARNING:[/bold yellow] PII samples shown below. "
            "Do not share this report without redacting sensitive data.",
            border_style="yellow",
            title="Privacy Warning",
        ))

    # Summary table
    summary = Table(title="PII Risk Indicators", show_lines=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Files scanned for PII", f"{pii.total_scanned:,}")
    summary.add_row("Files with PII indicators", f"{pii.files_with_pii:,}")
    if pii.scan_errors:
        summary.add_row("[yellow]Scan errors[/yellow]", f"{pii.scan_errors:,}")
    console.print(summary)

    # Per-type breakdown tables
    if not pii.per_type_counts:
        console.print(Text("  No PII risk indicators found.", style="dim"))
        console.print()
        return

    for pattern_name in pii.per_type_counts:
        label = pii.pattern_labels.get(pattern_name, pattern_name)
        match_count = pii.per_type_counts[pattern_name]
        file_count = pii.per_type_file_counts.get(pattern_name, 0)
        fp_rate = pii.pattern_fp_rates.get(pattern_name, 0.0)

        ci = compute_confidence_interval(
            file_count, pii.total_scanned, sample.total_population_size
        )

        table = Table(title=f"  {label}", show_lines=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Total matches", f"{match_count:,}")
        table.add_row("Files affected", f"{file_count:,}")
        table.add_row("Corpus exposure", format_ci(ci))
        if fp_rate > 0:
            table.add_row("Expected FP rate", f"~{fp_rate:.0%}")
        console.print(table)

    # Show sample matches if --show-pii-samples
    if pii.show_pii_samples:
        _render_pii_samples(pii, console)

    console.print()


def _render_language_encoding(
    language: LanguageResult | None,
    encoding: EncodingResult | None,
    sample: SampleResult | None,
    console: Console,
) -> None:
    """Render combined Language & Encoding section with two sub-tables."""
    # Language Distribution sub-table
    if language is not None and language.total_analyzed > 0:
        pop = sample.total_population_size if sample else language.total_analyzed

        table = Table(title="Language Distribution", show_lines=False)
        table.add_column("Language", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Proportion", justify="right")

        sorted_langs = sorted(
            language.language_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        displayed = sorted_langs[:10]
        remaining = sorted_langs[10:]

        for lang, count in displayed:
            ci = compute_confidence_interval(
                count, language.total_analyzed, pop
            )
            table.add_row(lang, f"{count:,}", format_ci(ci))

        if remaining:
            other_count = sum(c for _, c in remaining)
            ci = compute_confidence_interval(
                other_count, language.total_analyzed, pop
            )
            table.add_row(
                f"[dim]Other ({len(remaining)} languages)[/dim]",
                f"{other_count:,}",
                format_ci(ci),
            )

        console.print(table)
        if language.detection_errors:
            console.print(Text(
                f"  Detection errors: {language.detection_errors}",
                style="yellow",
            ))

    # Encoding Distribution sub-table
    if encoding is not None and encoding.total_analyzed > 0:
        table = Table(title="Encoding Distribution", show_lines=False)
        table.add_column("Encoding", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("%", justify="right")

        sorted_encs = sorted(
            encoding.encoding_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        for enc_name, count in sorted_encs:
            pct = count / encoding.total_analyzed * 100
            table.add_row(enc_name, f"{count:,}", f"{pct:.1f}%")

        console.print(table)
        console.print(Text(
            "  Encoding detected for plain text files only "
            "(PDF/DOCX handle encoding internally)",
            style="dim",
        ))

    console.print()


def _render_near_duplicates(
    simhash: SimHashResult,
    sample: SampleResult,
    walk_result: WalkResult,
    console: Console,
) -> None:
    """Render near-duplicate detection results with cluster list."""
    if simhash.total_analyzed == 0:
        return

    pop = sample.total_population_size

    # Summary table
    summary = Table(title="Near-Duplicate Detection (estimated)", show_lines=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Files analyzed", f"{simhash.total_analyzed:,}")
    summary.add_row("Near-duplicate clusters", f"{simhash.total_clusters:,}")
    summary.add_row("Files in clusters", f"{simhash.total_files_in_clusters:,}")

    if simhash.total_files_in_clusters > 0:
        ci = compute_confidence_interval(
            simhash.total_files_in_clusters, simhash.total_analyzed, pop
        )
        summary.add_row("Est. corpus near-dup %", format_ci(ci))

    console.print(summary)
    console.print(Text(
        f"  Near-duplicates detected via SimHash fingerprinting "
        f"(threshold: {simhash.threshold} bits)",
        style="dim",
    ))

    # Cluster detail table (top 5)
    if simhash.clusters:
        shown = min(5, len(simhash.clusters))
        detail = Table(
            title=f"Top Near-Duplicate Clusters "
                  f"(showing {shown} of {len(simhash.clusters)})",
            show_lines=False,
        )
        detail.add_column("Cluster", justify="right", style="cyan")
        detail.add_column("Files", justify="right")
        detail.add_column("Similarity", justify="right")
        detail.add_column("Paths")

        for idx, cluster in enumerate(simhash.clusters[:5], 1):
            sim_pct = f"{cluster.similarity * 100:.1f}%"

            # Show paths as relative to scan root, or basenames
            display_paths: list[str] = []
            for p in cluster.paths[:5]:
                try:
                    rel = Path(p).relative_to(walk_result.scan_root)
                    display_paths.append(str(rel))
                except ValueError:
                    display_paths.append(Path(p).name)

            path_str = "\n".join(display_paths)
            if len(cluster.paths) > 5:
                path_str += f"\n[dim]... and {len(cluster.paths) - 5} more[/dim]"

            detail.add_row(str(idx), str(len(cluster.paths)), sim_pct, path_str)

        console.print(detail)

    console.print()


def _render_pii_samples(pii: PIIScanResult, console: Console) -> None:
    """Render PII sample matches (only with --show-pii-samples)."""
    samples: list[tuple[str, str, str, int]] = []
    for fr in pii.file_results:
        for m in fr.sample_matches:
            samples.append((fr.path, m.pattern_name, m.matched_text, m.line_number))

    if not samples:
        return

    table = Table(title="PII Samples (first 5 per file)", show_lines=False)
    table.add_column("File", style="dim")
    table.add_column("Type")
    table.add_column("Match", style="red")
    table.add_column("Line", justify="right")

    for path, ptype, match, line in samples[:20]:
        short_path = Path(path).name
        label = pii.pattern_labels.get(ptype, ptype)
        table.add_row(short_path, label, match, str(line))

    console.print(table)
    if len(samples) > 20:
        console.print(Text(
            f"  ... and {len(samples) - 20} more matches", style="dim"
        ))
