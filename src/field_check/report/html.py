"""HTML report renderer using Jinja2."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import jinja2

from field_check import __version__
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
from field_check.scanner.sampling import SampleResult, compute_confidence_interval, format_ci
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import TextExtractionResult


def render_html_report(
    inventory: InventoryResult,
    walk_result: WalkResult,
    elapsed_seconds: float,
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
) -> str:
    """Render a complete report as self-contained HTML.

    Returns:
        HTML string with inline CSS and Chart.js.
    """
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("field_check", "templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    template = env.get_template("report.html")

    # Build context
    context = _build_context(
        inventory,
        walk_result,
        elapsed_seconds,
        dedup_result,
        corruption_result,
        sample_result,
        text_result,
        pii_result,
        language_result,
        encoding_result,
        simhash_result,
        mojibake_result,
        readability_result,
    )

    return template.render(**context)


def _build_context(
    inventory: InventoryResult,
    walk_result: WalkResult,
    elapsed_seconds: float,
    dedup: DedupResult | None,
    corruption: CorruptionResult | None,
    sample: SampleResult | None,
    text: TextExtractionResult | None,
    pii: PIIScanResult | None,
    language: LanguageResult | None,
    encoding: EncodingResult | None,
    simhash: SimHashResult | None,
    mojibake: MojibakeResult | None,
    readability: ReadabilityResult | None,
) -> dict:
    """Build the template context dict."""
    sd = inventory.size_distribution
    ad = inventory.age_distribution
    ds = inventory.dir_structure

    # Type distribution data
    sorted_types = sorted(inventory.type_counts.items(), key=lambda x: x[1], reverse=True)
    type_labels = [t for t, _ in sorted_types[:10]]
    type_counts = [c for _, c in sorted_types[:10]]
    type_rows = []
    for mime, count in sorted_types:
        pct = count / inventory.total_files * 100 if inventory.total_files else 0
        total_size = inventory.type_sizes.get(mime, 0)
        avg_size = total_size // count if count else 0
        type_rows.append(
            {
                "mime": mime,
                "count": count,
                "pct": f"{pct:.1f}",
                "total_size": format_size(total_size),
                "avg_size": format_size(avg_size),
            }
        )

    # Size distribution data
    size_labels = [b.label for b in sd.buckets]
    size_counts = [b.count for b in sd.buckets]

    context: dict = {
        "version": __version__,
        "scan_path": str(walk_result.scan_root),
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": format_duration(elapsed_seconds),
        "total_files": f"{inventory.total_files:,}",
        "total_size": format_size(inventory.total_size),
        "total_dirs": f"{ds.total_dirs:,}",
        # Type distribution
        "type_labels": type_labels,
        "type_counts": type_counts,
        "type_rows": type_rows,
        # Size distribution
        "size_labels": size_labels,
        "size_counts": size_counts,
        "size_stats": {
            "min": format_size(sd.min_size),
            "max": format_size(sd.max_size),
            "median": format_size(sd.median_size),
            "mean": format_size(sd.mean_size),
        },
        # Age distribution
        "age_rows": [
            {
                "label": b.label,
                "count": b.count,
                "pct": (
                    f"{b.count / inventory.total_files * 100:.1f}"
                    if inventory.total_files
                    else "0.0"
                ),
            }
            for b in ad.buckets
        ],
        "age_oldest": ad.oldest.strftime("%Y-%m-%d") if ad.oldest else None,
        "age_newest": ad.newest.strftime("%Y-%m-%d") if ad.newest else None,
        # Directory structure
        "dir_structure": {
            "total_dirs": f"{ds.total_dirs:,}",
            "max_depth": ds.max_depth,
            "avg_depth": f"{ds.avg_depth:.1f}",
            "max_breadth": f"{ds.max_breadth:,}",
            "avg_breadth": f"{ds.avg_breadth:.1f}",
            "empty_dirs": ds.empty_dirs,
        },
    }

    # Dedup section
    if dedup is not None:
        context["dedup"] = {
            "total_hashed": f"{dedup.total_hashed:,}",
            "unique_files": f"{dedup.unique_files:,}",
            "groups": f"{len(dedup.duplicate_groups):,}",
            "dup_files": f"{dedup.duplicate_file_count:,}",
            "wasted": format_size(dedup.duplicate_bytes),
            "pct": f"{dedup.duplicate_percentage:.1f}",
            "top_groups": [
                {
                    "hash": g.hash[:12],
                    "size": format_size(g.size),
                    "copies": len(g.paths),
                    "wasted": format_size(g.size * (len(g.paths) - 1)),
                    "paths": [str(_try_relative(p, walk_result.scan_root)) for p in g.paths[:5]],
                }
                for g in sorted(
                    dedup.duplicate_groups,
                    key=lambda g: g.size * (len(g.paths) - 1),
                    reverse=True,
                )[:10]
            ],
        }

    # Corruption section
    if corruption is not None:
        context["corruption"] = {
            "ok": f"{corruption.ok_count:,}",
            "empty": corruption.empty_count,
            "near_empty": corruption.near_empty_count,
            "corrupt": corruption.corrupt_count,
            "truncated": corruption.truncated_count,
            "encrypted": corruption.encrypted_count,
            "unreadable": corruption.unreadable_count,
        }

    # PII section (counts only — Invariant 3)
    if pii is not None and sample is not None:
        pii_types = []
        for pname in pii.per_type_counts:
            label = pii.pattern_labels.get(pname, pname)
            match_count = pii.per_type_counts[pname]
            file_count = pii.per_type_file_counts.get(pname, 0)
            ci = compute_confidence_interval(
                file_count, pii.total_scanned, sample.total_population_size
            )
            pii_types.append(
                {
                    "label": label,
                    "matches": f"{match_count:,}",
                    "files": f"{file_count:,}",
                    "exposure": format_ci(ci),
                }
            )
        context["pii"] = {
            "total_scanned": f"{pii.total_scanned:,}",
            "files_with_pii": f"{pii.files_with_pii:,}",
            "types": pii_types,
        }

    # Language section
    if language is not None and language.total_analyzed > 0:
        pop = sample.total_population_size if sample else language.total_analyzed
        sorted_langs = sorted(
            language.language_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        lang_labels = [name for name, _ in sorted_langs[:8]]
        lang_counts = [c for _, c in sorted_langs[:8]]
        lang_rows = []
        for lang, count in sorted_langs:
            ci = compute_confidence_interval(count, language.total_analyzed, pop)
            lang_rows.append(
                {
                    "language": lang,
                    "count": count,
                    "proportion": format_ci(ci),
                }
            )
        context["language"] = {
            "labels": lang_labels,
            "counts": lang_counts,
            "rows": lang_rows,
        }

    # Encoding section
    if encoding is not None and encoding.total_analyzed > 0:
        enc_pop = sample.total_population_size if sample else encoding.total_analyzed
        enc_rows = []
        for enc_name, count in sorted(
            encoding.encoding_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            ci = compute_confidence_interval(count, encoding.total_analyzed, enc_pop)
            enc_rows.append(
                {
                    "encoding": enc_name,
                    "count": count,
                    "proportion": format_ci(ci),
                }
            )
        context["encoding"] = {"rows": enc_rows}

    # Near-duplicates section
    if simhash is not None and sample is not None:
        clusters = []
        for idx, c in enumerate(simhash.clusters[:10], 1):
            paths = []
            for p in c.paths[:5]:
                paths.append(_try_relative_str(p, walk_result.scan_root))
            clusters.append(
                {
                    "num": idx,
                    "files": len(c.paths),
                    "similarity": f"{c.similarity * 100:.1f}",
                    "paths": paths,
                }
            )
        pop = sample.total_population_size
        nd_ci = None
        if simhash.total_files_in_clusters > 0:
            ci = compute_confidence_interval(
                simhash.total_files_in_clusters, simhash.total_analyzed, pop
            )
            nd_ci = format_ci(ci)
        context["simhash"] = {
            "total_analyzed": f"{simhash.total_analyzed:,}",
            "total_clusters": f"{simhash.total_clusters:,}",
            "files_in_clusters": f"{simhash.total_files_in_clusters:,}",
            "threshold": simhash.threshold,
            "corpus_pct": nd_ci,
            "clusters": clusters,
        }

    # Mojibake (encoding damage) section
    if mojibake is not None and mojibake.total_checked > 0:
        context["mojibake"] = {
            "total_checked": f"{mojibake.total_checked:,}",
            "files_with_mojibake": mojibake.files_with_mojibake,
            "files": [Path(p).name for p in mojibake.mojibake_files[:20]],
        }

    # Readability section
    if readability is not None and readability.total_checked > 0:
        context["readability"] = {
            "total_checked": f"{readability.total_checked:,}",
            "avg_flesch_score": f"{readability.avg_flesch_score:.1f}",
            "low_quality_count": readability.low_quality_count,
        }

    return context


def _try_relative(path: Path, root: Path) -> Path:
    """Try to make path relative to root, return as-is if not possible."""
    try:
        return Path(path).relative_to(root)
    except (ValueError, TypeError):
        return Path(path)


def _try_relative_str(path_str: str, root: Path) -> str:
    """Try to make path string relative to root."""
    try:
        return str(Path(path_str).relative_to(root))
    except (ValueError, TypeError):
        return Path(path_str).name
