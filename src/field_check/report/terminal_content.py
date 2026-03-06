"""Content-analysis sections for the terminal report.

Extracted from terminal.py to keep files under 500 lines.
Contains: text analysis, PII, language/encoding, and near-duplicate sections.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from field_check.scanner import WalkResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.mojibake import MojibakeResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.readability import ReadabilityResult
from field_check.scanner.sampling import (
    ConfidenceInterval,
    SampleResult,
    compute_confidence_interval,
    compute_confidence_interval_adjusted,
    format_ci,
)
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import METADATA_FIELDS, PAGE_COUNT_BUCKETS, TextExtractionResult


def _ci(
    successes: int,
    sample_size: int,
    pop_size: int,
    deff: float = 1.0,
) -> ConfidenceInterval:
    """Compute CI, applying DEFF adjustment when clustering is detected."""
    if deff > 1.0:
        return compute_confidence_interval_adjusted(
            successes,
            sample_size,
            pop_size,
            deff=deff,
        )
    return compute_confidence_interval(successes, sample_size, pop_size)


def render_text_analysis(
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
    render_scanned_detection(text, sample, console)

    # Content classification
    render_content_classification(text, sample, console)

    # Metadata completeness
    render_metadata_completeness(text, sample, console)

    # Page count distribution
    render_page_count_distribution(text, sample, console)

    console.print()


def render_scanned_detection(
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
            ci = _ci(count, total_classified, pdf_pop, sample.deff)
            table.add_row(label, f"{count:,}", format_ci(ci))

    console.print(table)


def render_content_classification(
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
            ci = _ci(count, total, pop, sample.deff)
            table.add_row(label, f"{count:,}", format_ci(ci))

    console.print(table)


def render_metadata_completeness(
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
        ci = _ci(count, n, pop, sample.deff)
        display_name = field_name.replace("_", " ").title()
        table.add_row(display_name, f"{count:,}", format_ci(ci))

    console.print(table)


def render_page_count_distribution(
    text: TextExtractionResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render page count distribution for documents with pages."""
    if not text.page_count_distribution:
        return

    total_docs_with_pages = sum(text.page_count_distribution.values())
    pop = sample.total_population_size if sample else total_docs_with_pages

    table = Table(title="Page Count Distribution", show_lines=False)
    table.add_column("Range", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Estimated %", justify="right")

    for _, _, label in PAGE_COUNT_BUCKETS:
        count = text.page_count_distribution.get(label, 0)
        if count > 0 or label in ("1 page", "2-5 pages"):
            ci = _ci(count, total_docs_with_pages, pop, sample.deff)
            table.add_row(label, f"{count:,}", format_ci(ci))

    console.print(table)
    if total_docs_with_pages > 0:
        mean = text.page_count_total / total_docs_with_pages
        console.print(
            Text(
                f"  Min: {text.page_count_min}  Max: {text.page_count_max}  Mean: {mean:.1f}",
                style="dim",
            )
        )


def render_pii_results(
    pii: PIIScanResult,
    sample: SampleResult,
    console: Console,
) -> None:
    """Render PII risk indicators with per-type breakdown."""
    if pii.total_scanned == 0:
        return

    # Warning banner if samples are shown
    if pii.show_pii_samples:
        console.print(
            Panel(
                "[bold yellow]WARNING:[/bold yellow] PII samples shown below. "
                "Do not share this report without redacting sensitive data.",
                border_style="yellow",
                title="Privacy Warning",
            )
        )

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

        ci = _ci(
            file_count,
            pii.total_scanned,
            sample.total_population_size,
            sample.deff,
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


def render_language_encoding(
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

        deff = sample.deff if sample else 1.0
        for lang, count in displayed:
            ci = _ci(count, language.total_analyzed, pop, deff)
            table.add_row(lang, f"{count:,}", format_ci(ci))

        if remaining:
            other_count = sum(c for _, c in remaining)
            ci = _ci(other_count, language.total_analyzed, pop, deff)
            table.add_row(
                f"[dim]Other ({len(remaining)} languages)[/dim]",
                f"{other_count:,}",
                format_ci(ci),
            )

        console.print(table)
        if language.detection_errors:
            console.print(
                Text(
                    f"  Detection errors: {language.detection_errors}",
                    style="yellow",
                )
            )

    # Encoding Distribution sub-table
    if encoding is not None and encoding.total_analyzed > 0:
        enc_pop = sample.total_population_size if sample else encoding.total_analyzed
        table = Table(title="Encoding Distribution", show_lines=False)
        table.add_column("Encoding", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Estimated %", justify="right")

        sorted_encs = sorted(
            encoding.encoding_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        enc_deff = sample.deff if sample else 1.0
        for enc_name, count in sorted_encs:
            ci = _ci(count, encoding.total_analyzed, enc_pop, enc_deff)
            table.add_row(enc_name, f"{count:,}", format_ci(ci))

        console.print(table)
        console.print(
            Text(
                "  Encoding detected for plain text files only "
                "(PDF/DOCX handle encoding internally)",
                style="dim",
            )
        )

    console.print()


def render_near_duplicates(
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
        ci = _ci(
            simhash.total_files_in_clusters,
            simhash.total_analyzed,
            pop,
            sample.deff,
        )
        summary.add_row("Est. corpus near-dup %", format_ci(ci))

    console.print(summary)
    console.print(
        Text(
            f"  Near-duplicates detected via SimHash fingerprinting "
            f"(threshold: {simhash.threshold} bits)",
            style="dim",
        )
    )

    # Cluster detail table (top 5)
    if simhash.clusters:
        shown = min(5, len(simhash.clusters))
        detail = Table(
            title=f"Top Near-Duplicate Clusters (showing {shown} of {len(simhash.clusters)})",
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


def render_mojibake_results(
    mojibake: MojibakeResult,
    console: Console,
) -> None:
    """Render encoding damage (mojibake) detection results."""
    if mojibake.total_checked == 0:
        return

    table = Table(title="Encoding Damage (Mojibake)", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Documents checked", f"{mojibake.total_checked:,}")
    table.add_row("With encoding damage", f"{mojibake.files_with_mojibake:,}")
    console.print(table)

    if mojibake.mojibake_files:
        detail = Table(
            title="Files with Encoding Damage (mojibake)",
            show_lines=False,
        )
        detail.add_column("Path", style="yellow")
        for p in mojibake.mojibake_files[:20]:
            detail.add_row(Path(p).name)
        console.print(detail)
        if len(mojibake.mojibake_files) > 20:
            console.print(
                Text(
                    f"  ... and {len(mojibake.mojibake_files) - 20} more",
                    style="dim",
                )
            )

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
        console.print(Text(f"  ... and {len(samples) - 20} more matches", style="dim"))


def render_readability_results(
    readability: ReadabilityResult,
    console: Console,
) -> None:
    """Render readability scoring results."""
    if readability.total_checked == 0:
        return

    table = Table(title="Readability Analysis", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Documents scored", f"{readability.total_checked:,}")
    table.add_row("Avg Flesch Reading Ease", f"{readability.avg_flesch_score:.1f}")
    table.add_row("Low quality (<30)", f"{readability.low_quality_count:,}")
    console.print(table)

    if readability.low_quality_count > 0:
        low_scores = [s for s in readability.scores if s.is_low_quality]
        low_scores.sort(key=lambda s: s.flesch_reading_ease)
        shown = low_scores[:10]

        detail = Table(
            title="Low Quality Documents (likely OCR garbage or binary)",
            show_lines=False,
        )
        detail.add_column("Path", style="yellow")
        detail.add_column("Flesch Score", justify="right")
        for s in shown:
            detail.add_row(Path(s.path).name, f"{s.flesch_reading_ease:.1f}")
        console.print(detail)
        if len(low_scores) > 10:
            console.print(
                Text(
                    f"  ... and {len(low_scores) - 10} more low-quality files",
                    style="dim",
                )
            )

    console.print()
