"""Text extraction pipeline with ProcessPoolExecutor crash isolation."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

from field_check.scanner import FileEntry
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.sampling import SampleResult

logger = logging.getLogger(__name__)

# MIME types that support text extraction
EXTRACTABLE_MIMES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/epub+zip",
    "message/rfc822",
}

# Standard metadata fields to check for completeness
METADATA_FIELDS: list[str] = ["title", "author", "creation_date"]

# Image-heavy classification thresholds
CHARS_PER_PAGE_IMAGE_HEAVY = 100
CHARS_PER_PAGE_TEXT_HEAVY = 500
TEXT_SIZE_RATIO_IMAGE_HEAVY = 0.05

# Classification labels
CLASSIFICATION_TEXT_HEAVY = "text_heavy"
CLASSIFICATION_IMAGE_HEAVY = "image_heavy"
CLASSIFICATION_MIXED = "mixed"

# Process pool defaults
DEFAULT_TIMEOUT = 30.0
MAX_WORKERS = 4

# Page count distribution buckets
PAGE_COUNT_BUCKETS: list[tuple[int, float, str]] = [
    (1, 1, "1 page"),
    (2, 5, "2-5 pages"),
    (6, 10, "6-10 pages"),
    (11, 50, "11-50 pages"),
    (51, 100, "51-100 pages"),
    (101, 500, "101-500 pages"),
    (501, float("inf"), ">500 pages"),
]

# MIME types for plain text content extraction
PLAIN_TEXT_MIMES: set[str] = {
    "text/plain",
    "text/csv",
    "text/json",
    "text/xml",
    "application/json",
    "application/xml",
}

# Combined set: all types we can extract text from for the cache
CACHE_EXTRACTABLE_MIMES: set[str] = EXTRACTABLE_MIMES | PLAIN_TEXT_MIMES

# Max bytes to read from plain text files
_MAX_TEXT_READ = 1_000_000


@dataclass
class TextResult:
    """Extraction result for a single file."""

    path: str
    text: str = ""
    text_length: int = 0
    page_count: int = 0
    chars_per_page: float = 0.0
    text_size_ratio: float = 0.0
    is_scanned: bool = False
    is_mixed_scan: bool = False
    classification: str = ""
    metadata: dict[str, str | None] = field(default_factory=dict)
    error: str | None = None


@dataclass
class TextExtractionResult:
    """Aggregate results from text extraction across sampled files."""

    total_processed: int = 0
    extraction_errors: int = 0
    timeout_errors: int = 0
    scanned_count: int = 0
    native_count: int = 0
    mixed_scan_count: int = 0
    text_heavy_count: int = 0
    image_heavy_count: int = 0
    mixed_content_count: int = 0
    metadata_field_counts: dict[str, int] = field(default_factory=dict)
    metadata_total_checked: int = 0
    page_count_total: int = 0
    page_count_min: int = 0
    page_count_max: int = 0
    page_count_distribution: dict[str, int] = field(default_factory=dict)
    file_results: list[TextResult] = field(default_factory=list)


@dataclass
class TextCacheResult:
    """Result of shared text cache extraction."""

    text_cache: dict[str, str] = field(default_factory=dict)
    encoding_map: dict[str, tuple[str, float]] = field(default_factory=dict)
    total_extracted: int = 0
    extraction_errors: int = 0


def _page_count_bucket(count: int) -> str:
    """Map a page count to its distribution bucket label."""
    for low, high, label in PAGE_COUNT_BUCKETS:
        if low <= count <= high:
            return label
    return ">500 pages"


def _aggregate_extraction(
    result: TextExtractionResult,
    text_result: TextResult,
    mime: str,
) -> None:
    """Aggregate a single file's extraction into the overall result."""
    # Scanned detection counts (PDF-only concept)
    if mime == "application/pdf":
        if text_result.is_scanned:
            result.scanned_count += 1
        elif text_result.is_mixed_scan:
            result.mixed_scan_count += 1
        else:
            result.native_count += 1

    # Content classification counts
    if text_result.classification == CLASSIFICATION_TEXT_HEAVY:
        result.text_heavy_count += 1
    elif text_result.classification == CLASSIFICATION_IMAGE_HEAVY:
        result.image_heavy_count += 1
    elif text_result.classification == CLASSIFICATION_MIXED:
        result.mixed_content_count += 1

    # Metadata completeness
    result.metadata_total_checked += 1
    for mf in METADATA_FIELDS:
        value = text_result.metadata.get(mf)
        if value:
            result.metadata_field_counts[mf] = (
                result.metadata_field_counts.get(mf, 0) + 1
            )

    # Page count distribution (PDF only)
    if text_result.page_count > 0:
        result.page_count_total += text_result.page_count
        if (
            result.page_count_min == 0
            or text_result.page_count < result.page_count_min
        ):
            result.page_count_min = text_result.page_count
        if text_result.page_count > result.page_count_max:
            result.page_count_max = text_result.page_count
        bucket = _page_count_bucket(text_result.page_count)
        result.page_count_distribution[bucket] = (
            result.page_count_distribution.get(bucket, 0) + 1
        )


def extract_text(
    sample: SampleResult,
    inventory: InventoryResult,
    max_workers: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> TextExtractionResult:
    """Extract text from sampled PDF/DOCX files using process pool.

    Uses ProcessPoolExecutor for crash isolation -- if a worker segfaults
    on a malformed file, the pool spawns a new worker automatically.

    Args:
        sample: Sampling result with selected files.
        inventory: Inventory with per-file MIME type mapping.
        max_workers: Max worker processes (default: min(4, cpu_count)).
        timeout: Per-file timeout in seconds.
        progress_callback: Called with (current, total) for progress display.

    Returns:
        Aggregated text extraction results.
    """
    from field_check.scanner.text_workers import _extract_single

    result = TextExtractionResult()

    # Filter to extractable types only
    extractable: list[tuple[FileEntry, str]] = []
    for entry in sample.selected_files:
        mime = inventory.file_types.get(entry.path, "application/octet-stream")
        if mime in EXTRACTABLE_MIMES:
            extractable.append((entry, mime))

    if not extractable:
        return result

    total = len(extractable)
    workers = max_workers or min(MAX_WORKERS, os.cpu_count() or 1)

    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_info: dict = {}
        for entry, mime in extractable:
            future = pool.submit(_extract_single, str(entry.path), mime)
            future_to_info[future] = (entry, mime)

        for completed, future in enumerate(as_completed(future_to_info), 1):
            entry, mime = future_to_info[future]
            try:
                text_result = future.result(timeout=timeout)
            except TimeoutError:
                text_result = TextResult(
                    path=str(entry.path), error="Extraction timed out"
                )
                result.timeout_errors += 1
            except Exception as exc:
                text_result = TextResult(
                    path=str(entry.path), error=str(exc)
                )

            result.file_results.append(text_result)
            result.total_processed += 1

            if text_result.error:
                result.extraction_errors += 1
            else:
                _aggregate_extraction(result, text_result, mime)

            if progress_callback is not None:
                progress_callback(completed, total)

    return result


def build_text_cache(
    sample: SampleResult,
    inventory: InventoryResult,
    max_workers: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> TextCacheResult:
    """Build shared text cache for downstream analysis.

    Uses ProcessPoolExecutor for crash isolation. Extracts text from:
    - PDFs via pdfplumber
    - DOCXes via python-docx
    - Plain text files via charset-normalizer (also captures encoding)

    Args:
        sample: Sampling result with selected files.
        inventory: Inventory with per-file MIME type mapping.
        max_workers: Max worker processes.
        timeout: Per-file timeout in seconds.
        progress_callback: Called with (current, total).

    Returns:
        TextCacheResult with text_cache dict and encoding_map.
    """
    from field_check.scanner.text_workers import _extract_text_for_cache

    cache_result = TextCacheResult()

    # Filter to cache-extractable types
    extractable: list[tuple[FileEntry, str]] = []
    for entry in sample.selected_files:
        mime = inventory.file_types.get(entry.path, "application/octet-stream")
        if mime in CACHE_EXTRACTABLE_MIMES:
            extractable.append((entry, mime))

    if not extractable:
        return cache_result

    total = len(extractable)
    workers = max_workers or min(MAX_WORKERS, os.cpu_count() or 1)

    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_entry: dict = {}
        for entry, mime in extractable:
            future = pool.submit(
                _extract_text_for_cache, str(entry.path), mime
            )
            future_to_entry[future] = entry

        for completed, future in enumerate(as_completed(future_to_entry), 1):
            entry = future_to_entry[future]
            path_str = str(entry.path)
            try:
                text, enc_name, enc_conf, error = future.result(
                    timeout=timeout
                )
            except TimeoutError:
                cache_result.extraction_errors += 1
                cache_result.total_extracted += 1
                if progress_callback is not None:
                    progress_callback(completed, total)
                continue
            except Exception:
                cache_result.extraction_errors += 1
                cache_result.total_extracted += 1
                if progress_callback is not None:
                    progress_callback(completed, total)
                continue

            cache_result.total_extracted += 1

            if error:
                cache_result.extraction_errors += 1
            else:
                if text:
                    cache_result.text_cache[path_str] = text
                if enc_name:
                    cache_result.encoding_map[path_str] = (
                        enc_name,
                        enc_conf,
                    )

            if progress_callback is not None:
                progress_callback(completed, total)

    return cache_result


def extract_text_unified(
    sample: SampleResult,
    inventory: InventoryResult,
    max_workers: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[TextExtractionResult, TextCacheResult]:
    """Single-pass text extraction for metadata analysis and text cache.

    Eliminates double PDF/DOCX parsing by retaining extracted text in
    TextResult.text and populating the text cache from it. Plain text
    files are extracted separately for encoding detection.

    Args:
        sample: Sampling result with selected files.
        inventory: Inventory with per-file MIME type mapping.
        max_workers: Max worker processes (default: min(4, cpu_count)).
        timeout: Per-file timeout in seconds.
        progress_callback: Called with (current, total) for progress display.

    Returns:
        Tuple of (TextExtractionResult, TextCacheResult).
    """
    from field_check.scanner.text_workers import (
        _extract_plain_text,
        _extract_single,
    )

    text_result = TextExtractionResult()
    cache_result = TextCacheResult()

    # Separate files into PDF/DOCX (rich extraction) and plain text
    pdf_docx: list[tuple[FileEntry, str]] = []
    plain_text: list[tuple[FileEntry, str]] = []

    for entry in sample.selected_files:
        mime = inventory.file_types.get(entry.path, "application/octet-stream")
        if mime in EXTRACTABLE_MIMES:
            pdf_docx.append((entry, mime))
        elif mime in PLAIN_TEXT_MIMES:
            plain_text.append((entry, mime))

    total = len(pdf_docx) + len(plain_text)
    if total == 0:
        return text_result, cache_result

    workers = max_workers or min(MAX_WORKERS, os.cpu_count() or 1)
    completed = 0

    # Phase A: PDF/DOCX — metadata + classification + text in one pass
    if pdf_docx:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_info: dict = {}
            for entry, mime in pdf_docx:
                future = pool.submit(
                    _extract_single, str(entry.path), mime
                )
                future_to_info[future] = (entry, mime)

            for future in as_completed(future_to_info):
                entry, mime = future_to_info[future]
                try:
                    file_result = future.result(timeout=timeout)
                except TimeoutError:
                    file_result = TextResult(
                        path=str(entry.path), error="Extraction timed out"
                    )
                    text_result.timeout_errors += 1
                except Exception as exc:
                    file_result = TextResult(
                        path=str(entry.path), error=str(exc)
                    )

                text_result.file_results.append(file_result)
                text_result.total_processed += 1

                if file_result.error:
                    text_result.extraction_errors += 1
                    cache_result.extraction_errors += 1
                else:
                    _aggregate_extraction(text_result, file_result, mime)
                    if file_result.text:
                        cache_result.text_cache[str(entry.path)] = (
                            file_result.text
                        )
                cache_result.total_extracted += 1

                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total)

    # Phase B: Plain text — encoding detection + text cache
    if plain_text:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_entry: dict = {}
            for entry, _mime in plain_text:
                future = pool.submit(
                    _extract_plain_text, str(entry.path)
                )
                future_to_entry[future] = entry

            for future in as_completed(future_to_entry):
                entry = future_to_entry[future]
                path_str = str(entry.path)
                try:
                    text, enc_name, enc_conf, error = future.result(
                        timeout=timeout
                    )
                except (TimeoutError, Exception):
                    cache_result.extraction_errors += 1
                    cache_result.total_extracted += 1
                    completed += 1
                    if progress_callback is not None:
                        progress_callback(completed, total)
                    continue

                cache_result.total_extracted += 1

                if error:
                    cache_result.extraction_errors += 1
                else:
                    if text:
                        cache_result.text_cache[path_str] = text
                    if enc_name:
                        cache_result.encoding_map[path_str] = (
                            enc_name,
                            enc_conf,
                        )

                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total)

    return text_result, cache_result
