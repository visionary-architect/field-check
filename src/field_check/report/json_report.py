"""JSON report renderer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from field_check import __version__
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.mojibake import MojibakeResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.readability import ReadabilityResult
from field_check.scanner.sampling import SampleResult, compute_confidence_interval
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import TextExtractionResult


def render_json_report(
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
    """Render a complete report as JSON.

    Returns:
        Pretty-printed JSON string.
    """
    # Build per-file lookup dicts
    hash_lookup = _build_hash_lookup(walk_result, dedup_result)
    dup_paths = _build_duplicate_paths(dedup_result)
    health_lookup = _build_health_lookup(corruption_result)
    pii_lookup = _build_pii_lookup(pii_result)
    lang_lookup = _build_language_lookup(language_result)
    enc_lookup = _build_encoding_lookup(encoding_result)

    data = {
        "version": __version__,
        "scan_path": str(walk_result.scan_root),
        "scan_date": datetime.now().isoformat(),
        "duration_seconds": round(elapsed_seconds, 3),
        "summary": _build_summary(
            inventory, walk_result, dedup_result, corruption_result,
            sample_result, text_result, pii_result, language_result,
            encoding_result, simhash_result, mojibake_result,
            readability_result,
        ),
        "files": _build_files_array(
            walk_result, inventory, hash_lookup, dup_paths,
            health_lookup, pii_lookup, lang_lookup, enc_lookup,
        ),
    }

    return json.dumps(data, indent=2, ensure_ascii=False)


def _build_summary(
    inventory: InventoryResult,
    walk_result: WalkResult,
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
    """Build the summary section of the JSON report."""
    sd = inventory.size_distribution
    ad = inventory.age_distribution
    ds = inventory.dir_structure

    summary: dict = {
        "total_files": inventory.total_files,
        "total_size": inventory.total_size,
        "type_distribution": dict(inventory.type_counts),
        "size_distribution": {
            "buckets": [
                {"label": b.label, "count": b.count}
                for b in sd.buckets
            ],
            "min": sd.min_size,
            "max": sd.max_size,
            "median": sd.median_size,
            "mean": round(sd.mean_size, 2),
        },
        "age_distribution": {
            "buckets": [
                {"label": b.label, "count": b.count}
                for b in ad.buckets
            ],
            "oldest": ad.oldest.isoformat() if ad.oldest else None,
            "newest": ad.newest.isoformat() if ad.newest else None,
        },
        "directory_structure": {
            "total_dirs": ds.total_dirs,
            "max_depth": ds.max_depth,
            "avg_depth": round(ds.avg_depth, 1),
            "max_breadth": ds.max_breadth,
            "avg_breadth": round(ds.avg_breadth, 1),
            "empty_dirs": ds.empty_dirs,
        },
    }

    # Duplicates
    if dedup is not None:
        summary["duplicates"] = {
            "total_hashed": dedup.total_hashed,
            "unique_files": dedup.unique_files,
            "duplicate_groups": len(dedup.duplicate_groups),
            "duplicate_files": dedup.duplicate_file_count,
            "duplicate_bytes": dedup.duplicate_bytes,
            "duplicate_percentage": round(dedup.duplicate_percentage, 2),
        }
    else:
        summary["duplicates"] = None

    # Corruption
    if corruption is not None:
        summary["corruption"] = {
            "total_checked": corruption.total_checked,
            "ok": corruption.ok_count,
            "empty": corruption.empty_count,
            "near_empty": corruption.near_empty_count,
            "corrupt": corruption.corrupt_count,
            "truncated": corruption.truncated_count,
            "encrypted": corruption.encrypted_count,
            "unreadable": corruption.unreadable_count,
        }
    else:
        summary["corruption"] = None

    # PII (counts only — Invariant 3: no matched content)
    if pii is not None:
        summary["pii"] = {
            "total_scanned": pii.total_scanned,
            "files_with_pii": pii.files_with_pii,
            "per_type_counts": dict(pii.per_type_counts),
            "per_type_file_counts": dict(pii.per_type_file_counts),
            "scan_errors": pii.scan_errors,
        }
    else:
        summary["pii"] = None

    # Language
    if language is not None:
        pop = sample.total_population_size if sample else language.total_analyzed
        lang_ci = {}
        for lang, count in language.language_distribution.items():
            ci = compute_confidence_interval(count, language.total_analyzed, pop)
            lang_ci[lang] = {
                "count": count,
                "point_estimate": round(ci.point_estimate * 100, 2),
                "lower_bound": round(ci.lower * 100, 2),
                "upper_bound": round(ci.upper * 100, 2),
            }
        summary["language"] = {
            "total_analyzed": language.total_analyzed,
            "distribution": dict(language.language_distribution),
            "distribution_ci": lang_ci,
            "detection_errors": language.detection_errors,
        }
    else:
        summary["language"] = None

    # Encoding
    if encoding is not None:
        enc_pop = sample.total_population_size if sample else encoding.total_analyzed
        enc_ci = {}
        for enc_name, count in encoding.encoding_distribution.items():
            ci = compute_confidence_interval(
                count, encoding.total_analyzed, enc_pop
            )
            enc_ci[enc_name] = {
                "count": count,
                "point_estimate": round(ci.point_estimate * 100, 2),
                "lower_bound": round(ci.lower * 100, 2),
                "upper_bound": round(ci.upper * 100, 2),
            }
        summary["encoding"] = {
            "total_analyzed": encoding.total_analyzed,
            "distribution": dict(encoding.encoding_distribution),
            "distribution_ci": enc_ci,
            "detection_errors": encoding.detection_errors,
        }
    else:
        summary["encoding"] = None

    # Near-duplicates
    if simhash is not None:
        summary["near_duplicates"] = {
            "total_analyzed": simhash.total_analyzed,
            "total_clusters": simhash.total_clusters,
            "files_in_clusters": simhash.total_files_in_clusters,
            "threshold": simhash.threshold,
            "clusters": [
                {
                    "files": len(c.paths),
                    "similarity": round(c.similarity, 4),
                    "paths": [
                        _try_relative(p, walk_result.scan_root)
                        for p in c.paths
                    ],
                }
                for c in simhash.clusters
            ],
        }
    else:
        summary["near_duplicates"] = None

    # Mojibake (encoding damage)
    if mojibake is not None:
        summary["mojibake"] = {
            "total_checked": mojibake.total_checked,
            "files_with_mojibake": mojibake.files_with_mojibake,
            "affected_files": mojibake.mojibake_files,
        }
    else:
        summary["mojibake"] = None

    # Readability
    if readability is not None and readability.total_checked > 0:
        summary["readability"] = {
            "total_checked": readability.total_checked,
            "avg_flesch_score": readability.avg_flesch_score,
            "low_quality_count": readability.low_quality_count,
        }
    else:
        summary["readability"] = None

    return summary


def _try_relative(p: str, root: Path) -> str:
    """Return path relative to root if possible, otherwise the original."""
    try:
        return str(Path(p).relative_to(root))
    except ValueError:
        return p


def _build_hash_lookup(
    walk_result: WalkResult,
    dedup: DedupResult | None,
) -> dict[str, str]:
    """Build path → blake3 hash lookup from dedup result."""
    lookup: dict[str, str] = {}
    if dedup is None:
        return lookup
    for group in dedup.duplicate_groups:
        for p in group.paths:
            lookup[str(p)] = group.hash
    # Also need hashes for non-duplicate files — but dedup only stores groups.
    # We don't have single-file hashes stored. Return what we have.
    return lookup


def _build_duplicate_paths(dedup: DedupResult | None) -> set[str]:
    """Build set of paths that are duplicates."""
    paths: set[str] = set()
    if dedup is None:
        return paths
    for group in dedup.duplicate_groups:
        for p in group.paths:
            paths.add(str(p))
    return paths


def _build_health_lookup(
    corruption: CorruptionResult | None,
) -> dict[str, str]:
    """Build path → health status lookup."""
    lookup: dict[str, str] = {}
    if corruption is None:
        return lookup
    for fh in corruption.flagged_files:
        lookup[str(fh.path)] = fh.status
    return lookup


def _build_pii_lookup(
    pii: PIIScanResult | None,
) -> dict[str, list[str]]:
    """Build path → list of PII pattern types lookup."""
    lookup: dict[str, list[str]] = {}
    if pii is None:
        return lookup
    for fr in pii.file_results:
        if fr.matches_by_type:
            lookup[fr.path] = list(fr.matches_by_type.keys())
    return lookup


def _build_language_lookup(
    language: LanguageResult | None,
) -> dict[str, str]:
    """Build path → detected language lookup."""
    lookup: dict[str, str] = {}
    if language is None:
        return lookup
    for fr in language.file_results:
        lookup[fr.path] = fr.language
    return lookup


def _build_encoding_lookup(
    encoding: EncodingResult | None,
) -> dict[str, str]:
    """Build path → detected encoding lookup."""
    lookup: dict[str, str] = {}
    if encoding is None:
        return lookup
    for fr in encoding.file_results:
        lookup[fr.path] = fr.encoding
    return lookup


def _build_files_array(
    walk_result: WalkResult,
    inventory: InventoryResult,
    hash_lookup: dict[str, str],
    dup_paths: set[str],
    health_lookup: dict[str, str],
    pii_lookup: dict[str, list[str]],
    lang_lookup: dict[str, str],
    enc_lookup: dict[str, str],
) -> list[dict]:
    """Build the per-file data array."""
    files = []
    for entry in walk_result.files:
        path_str = str(entry.path)
        rel_path = str(entry.relative_path)

        pii_types = pii_lookup.get(path_str)

        files.append({
            "path": rel_path,
            "size": entry.size,
            "mime_type": inventory.file_types.get(entry.path, "unknown"),
            "blake3": hash_lookup.get(path_str),
            "is_duplicate": path_str in dup_paths,
            "health_status": health_lookup.get(path_str, "ok"),
            "has_pii": pii_types is not None and len(pii_types) > 0,
            "pii_types": pii_types,
            "language": lang_lookup.get(path_str),
            "encoding": enc_lookup.get(path_str),
        })

    return files
