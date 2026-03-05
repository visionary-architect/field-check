"""PII regex scanning with Luhn validation and ProcessPoolExecutor isolation."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

from field_check.config import FieldCheckConfig
from field_check.scanner import FileEntry
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.sampling import SampleResult

logger = logging.getLogger(__name__)

# Built-in PII patterns with expected false positive rates
BUILTIN_PATTERNS: list[dict[str, str | float]] = [
    {
        "name": "email",
        "label": "Email Address",
        "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "fp_rate": 0.10,
    },
    {
        "name": "credit_card",
        "label": "Credit Card Number",
        "pattern": r"\b(?:\d[ -]*?){13,19}\b",
        "fp_rate": 0.20,
        "validator": "luhn",
    },
    {
        "name": "ssn",
        "label": "SSN (US)",
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "fp_rate": 0.40,
    },
    {
        "name": "phone",
        "label": "Phone Number",
        "pattern": (
            r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)"
            r"\d{3}[-.\s]?\d{4}\b"
        ),
        "fp_rate": 0.50,
    },
    {
        "name": "ip_address",
        "label": "IP Address",
        "pattern": (
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        "fp_rate": 0.15,
    },
]

# MIME types that PII scanner can extract text from
PII_EXTRACTABLE_MIMES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/csv",
    "text/json",
    "text/xml",
    "application/json",
    "application/xml",
}

# Max bytes to read from plain text files
_MAX_TEXT_READ = 1_000_000

# Max worker processes
_MAX_WORKERS = 4

# Default per-file timeout
_DEFAULT_TIMEOUT = 30.0


@dataclass
class PIIMatch:
    """A single PII match in a file."""

    pattern_name: str
    matched_text: str
    line_number: int


@dataclass
class PIIFileResult:
    """PII scan result for a single file."""

    path: str
    matches_by_type: dict[str, int] = field(default_factory=dict)
    sample_matches: list[PIIMatch] = field(default_factory=list)
    error: str | None = None


@dataclass
class PIIScanResult:
    """Aggregate PII scan results."""

    total_scanned: int = 0
    files_with_pii: int = 0
    per_type_counts: dict[str, int] = field(default_factory=dict)
    per_type_file_counts: dict[str, int] = field(default_factory=dict)
    pattern_labels: dict[str, str] = field(default_factory=dict)
    pattern_fp_rates: dict[str, float] = field(default_factory=dict)
    file_results: list[PIIFileResult] = field(default_factory=list)
    scan_errors: int = 0
    show_pii_samples: bool = False


def _luhn_check(number_str: str) -> bool:
    """Validate a number string using the Luhn algorithm.

    Args:
        number_str: String potentially containing a credit card number.

    Returns:
        True if the digits pass the Luhn checksum.
    """
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _extract_text_for_pii(filepath: str, mime_type: str) -> str:
    """Extract text content from a file for PII scanning.

    For PDF/DOCX: uses pdfplumber/python-docx.
    For plain text types: reads raw bytes with charset-normalizer.

    Args:
        filepath: Absolute path to the file.
        mime_type: MIME type of the file.

    Returns:
        Extracted text content as a string.
    """
    if mime_type == "application/pdf":
        import pdfplumber

        with pdfplumber.open(filepath) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    elif (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        from docx import Document

        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        # Plain text types — read bytes, detect encoding
        from charset_normalizer import from_bytes

        with open(filepath, "rb") as f:
            raw = f.read(_MAX_TEXT_READ)
        result = from_bytes(raw).best()
        return str(result) if result else raw.decode("utf-8", errors="replace")


def _scan_single_file(
    filepath: str,
    mime_type: str,
    compiled_patterns: list[tuple[str, str, re.Pattern[str], str | None]],
    show_samples: bool,
) -> PIIFileResult:
    """Scan a single file for PII patterns.

    Args:
        filepath: Path to the file.
        mime_type: MIME type for extraction dispatch.
        compiled_patterns: List of (name, label, pattern, validator) tuples.
        show_samples: Whether to store matched content.

    Returns:
        PII scan result for this file.
    """
    file_result = PIIFileResult(path=filepath)
    try:
        text = _extract_text_for_pii(filepath, mime_type)
        if not text:
            return file_result

        for line_num, line in enumerate(text.split("\n"), 1):
            for name, _label, pattern, validator in compiled_patterns:
                for match in pattern.finditer(line):
                    matched = match.group()
                    if validator == "luhn" and not _luhn_check(matched):
                        continue
                    file_result.matches_by_type[name] = (
                        file_result.matches_by_type.get(name, 0) + 1
                    )
                    if show_samples and len(file_result.sample_matches) < 5:
                        file_result.sample_matches.append(
                            PIIMatch(
                                pattern_name=name,
                                matched_text=matched,
                                line_number=line_num,
                            )
                        )
    except Exception as exc:
        file_result.error = str(exc)
    return file_result


def _scan_single_file_from_specs(
    filepath: str,
    mime_type: str,
    pattern_specs: list[tuple[str, str, str, str | None]],
    show_samples: bool,
) -> PIIFileResult:
    """Worker entry point for ProcessPoolExecutor.

    Compiles patterns from serializable specs (re.Pattern can't be pickled),
    then delegates to _scan_single_file.
    """
    compiled = [
        (name, label, re.compile(pat_str), validator)
        for name, label, pat_str, validator in pattern_specs
    ]
    return _scan_single_file(filepath, mime_type, compiled, show_samples)


def _scan_text_for_pii(
    filepath: str,
    text: str,
    compiled_patterns: list[tuple[str, str, re.Pattern[str], str | None]],
    show_samples: bool,
) -> PIIFileResult:
    """Scan pre-extracted text for PII patterns (no file I/O).

    Used when text is available from the shared text cache.

    Args:
        filepath: Path to the file (for result metadata).
        text: Pre-extracted text content.
        compiled_patterns: List of (name, label, pattern, validator) tuples.
        show_samples: Whether to store matched content.

    Returns:
        PII scan result for this file.
    """
    file_result = PIIFileResult(path=filepath)
    if not text:
        return file_result

    for line_num, line in enumerate(text.split("\n"), 1):
        for name, _label, pattern, validator in compiled_patterns:
            for match in pattern.finditer(line):
                matched = match.group()
                if validator == "luhn" and not _luhn_check(matched):
                    continue
                file_result.matches_by_type[name] = (
                    file_result.matches_by_type.get(name, 0) + 1
                )
                if show_samples and len(file_result.sample_matches) < 5:
                    file_result.sample_matches.append(
                        PIIMatch(
                            pattern_name=name,
                            matched_text=matched,
                            line_number=line_num,
                        )
                    )

    return file_result


def scan_pii(
    sample: SampleResult,
    inventory: InventoryResult,
    config: FieldCheckConfig,
    text_cache: dict[str, str] | None = None,
    max_workers: int | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> PIIScanResult:
    """Scan sampled files for PII patterns.

    When text_cache is provided, uses pre-extracted text (no file I/O).
    Otherwise falls back to ProcessPoolExecutor with per-file extraction.

    Args:
        sample: Sampling result with selected files.
        inventory: Inventory with per-file MIME type mapping.
        config: Configuration with custom patterns and show_pii_samples flag.
        text_cache: Pre-extracted text dict from build_text_cache() (optional).
        max_workers: Max worker processes (default: min(4, cpu_count)).
        timeout: Per-file timeout in seconds.
        progress_callback: Called with (current, total) for progress display.

    Returns:
        Aggregated PII scan results.
    """
    result = PIIScanResult(show_pii_samples=config.show_pii_samples)

    # Build pattern list: built-in + custom
    pattern_specs: list[tuple[str, str, str, str | None]] = []
    for p in BUILTIN_PATTERNS:
        name = str(p["name"])
        label = str(p["label"])
        pattern_str = str(p["pattern"])
        validator = str(p["validator"]) if "validator" in p else None
        pattern_specs.append((name, label, pattern_str, validator))
        result.pattern_labels[name] = label
        result.pattern_fp_rates[name] = float(p.get("fp_rate", 0.0))

    for custom in config.pii_custom_patterns:
        name = custom["name"]
        pattern_specs.append((name, name, custom["pattern"], None))
        result.pattern_labels[name] = name
        result.pattern_fp_rates[name] = 0.0

    # Filter to PII-extractable files from sample
    extractable: list[tuple[FileEntry, str]] = []
    for entry in sample.selected_files:
        mime = inventory.file_types.get(entry.path, "application/octet-stream")
        if mime in PII_EXTRACTABLE_MIMES:
            extractable.append((entry, mime))

    if not extractable:
        return result

    total = len(extractable)

    # Compile patterns for direct scanning (used with text_cache)
    compiled_patterns = [
        (name, label, re.compile(pat_str), validator)
        for name, label, pat_str, validator in pattern_specs
    ]

    # Split into cached (direct scan) and uncached (process pool)
    cached_entries: list[tuple[FileEntry, str]] = []
    uncached_entries: list[tuple[FileEntry, str]] = []

    if text_cache:
        for entry, mime in extractable:
            if str(entry.path) in text_cache:
                cached_entries.append((entry, mime))
            else:
                uncached_entries.append((entry, mime))
    else:
        uncached_entries = extractable

    completed_count = 0

    # Scan cached files directly (no process pool, no file I/O)
    for entry, _mime in cached_entries:
        path_str = str(entry.path)
        file_result = _scan_text_for_pii(
            path_str,
            text_cache[path_str],  # type: ignore[index]
            compiled_patterns,
            config.show_pii_samples,
        )
        _aggregate_file_result(result, file_result)
        completed_count += 1
        if progress_callback is not None:
            progress_callback(completed_count, total)

    # Scan uncached files via ProcessPoolExecutor (with file I/O)
    if uncached_entries:
        workers = max_workers or min(_MAX_WORKERS, os.cpu_count() or 1)

        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_entry: dict = {}
            for entry, mime in uncached_entries:
                future = pool.submit(
                    _scan_single_file_from_specs,
                    str(entry.path),
                    mime,
                    pattern_specs,
                    config.show_pii_samples,
                )
                future_to_entry[future] = entry

            for future in as_completed(future_to_entry):
                try:
                    file_result = future.result(timeout=timeout)
                except TimeoutError:
                    file_result = PIIFileResult(
                        path=str(future_to_entry[future].path),
                        error="PII scan timed out",
                    )
                    result.scan_errors += 1
                except Exception as exc:
                    file_result = PIIFileResult(
                        path=str(future_to_entry[future].path),
                        error=str(exc),
                    )
                    result.scan_errors += 1

                _aggregate_file_result(result, file_result)
                completed_count += 1
                if progress_callback is not None:
                    progress_callback(completed_count, total)

    return result


def _aggregate_file_result(result: PIIScanResult, file_result: PIIFileResult) -> None:
    """Aggregate a single file result into the scan result."""
    result.file_results.append(file_result)
    result.total_scanned += 1

    if file_result.error:
        result.scan_errors += 1
    elif file_result.matches_by_type:
        result.files_with_pii += 1
        for pname, count in file_result.matches_by_type.items():
            result.per_type_counts[pname] = (
                result.per_type_counts.get(pname, 0) + count
            )
            result.per_type_file_counts[pname] = (
                result.per_type_file_counts.get(pname, 0) + 1
            )
