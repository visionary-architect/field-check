"""CSV report renderer."""

from __future__ import annotations

import csv
import io

from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.sampling import SampleResult
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import TextExtractionResult

CSV_COLUMNS = [
    "path",
    "size",
    "mime_type",
    "blake3",
    "is_duplicate",
    "health_status",
    "has_pii",
    "pii_types",
    "language",
    "encoding",
]


def render_csv_report(
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
) -> str:
    """Render a file-level inventory as CSV.

    Returns:
        CSV string with header row and one row per file.
    """
    # Build per-file lookup dicts
    dup_paths = _build_duplicate_paths(dedup_result)
    hash_lookup = _build_hash_lookup(dedup_result)
    health_lookup = _build_health_lookup(corruption_result)
    pii_lookup = _build_pii_lookup(pii_result)
    lang_lookup = _build_language_lookup(language_result)
    enc_lookup = _build_encoding_lookup(encoding_result)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)

    for entry in walk_result.files:
        path_str = str(entry.path)
        pii_types = pii_lookup.get(path_str, [])

        writer.writerow([
            str(entry.relative_path),
            entry.size,
            inventory.file_types.get(entry.path, "unknown"),
            hash_lookup.get(path_str, ""),
            path_str in dup_paths,
            health_lookup.get(path_str, "ok"),
            len(pii_types) > 0,
            ";".join(pii_types) if pii_types else "",
            lang_lookup.get(path_str, ""),
            enc_lookup.get(path_str, ""),
        ])

    return output.getvalue()


def _build_duplicate_paths(dedup: DedupResult | None) -> set[str]:
    """Build set of paths that are duplicates."""
    paths: set[str] = set()
    if dedup is None:
        return paths
    for group in dedup.duplicate_groups:
        for p in group.paths:
            paths.add(str(p))
    return paths


def _build_hash_lookup(dedup: DedupResult | None) -> dict[str, str]:
    """Build path → blake3 hash lookup from dedup result."""
    lookup: dict[str, str] = {}
    if dedup is None:
        return lookup
    for group in dedup.duplicate_groups:
        for p in group.paths:
            lookup[str(p)] = group.hash
    return lookup


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
