"""CSV report renderer."""

from __future__ import annotations

import csv
import io

from field_check.report.utils import (
    build_duplicate_paths,
    build_encoding_lookup,
    build_hash_lookup,
    build_health_lookup,
    build_language_lookup,
    build_pii_lookup,
)
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


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "|")


def _sanitize_csv_cell(value: str) -> str:
    """Prefix formula-triggering characters to prevent CSV injection in spreadsheets."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


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
    mojibake_result: MojibakeResult | None = None,
    readability_result: ReadabilityResult | None = None,
) -> str:
    """Render a file-level inventory as CSV.

    Returns:
        CSV string with header row and one row per file.
    """
    # Build per-file lookup dicts
    dup_paths = build_duplicate_paths(dedup_result)
    hash_lookup = build_hash_lookup(dedup_result)
    health_lookup = build_health_lookup(corruption_result)
    pii_lookup = build_pii_lookup(pii_result)
    lang_lookup = build_language_lookup(language_result)
    enc_lookup = build_encoding_lookup(encoding_result)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)

    for entry in walk_result.files:
        path_str = str(entry.path)
        pii_types = pii_lookup.get(path_str, [])

        writer.writerow(
            [
                _sanitize_csv_cell(str(entry.relative_path)),
                entry.size,
                _sanitize_csv_cell(inventory.file_types.get(entry.path, "unknown")),
                _sanitize_csv_cell(hash_lookup.get(path_str, "")),
                path_str in dup_paths,
                _sanitize_csv_cell(health_lookup.get(path_str, "ok")),
                len(pii_types) > 0,
                _sanitize_csv_cell(";".join(pii_types)) if pii_types else "",
                _sanitize_csv_cell(lang_lookup.get(path_str, "")),
                _sanitize_csv_cell(enc_lookup.get(path_str, "")),
            ]
        )

    return "\ufeff" + output.getvalue()
