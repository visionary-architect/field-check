"""Encoding detection result aggregation for plain text files."""

from __future__ import annotations

import codecs
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Display name overrides applied after codecs.lookup() normalization.
# codecs.lookup handles all alias→canonical mapping; this dict only
# covers cases where we want a different display name.
_DISPLAY_OVERRIDES: dict[str, str] = {
    "ascii": "utf-8",  # ASCII is a subset of UTF-8
    "utf-8-sig": "utf-8",  # UTF-8 with BOM
    "cp1252": "windows-1252",
    "iso8859-1": "iso-8859-1",
    "iso8859-15": "iso-8859-15",
}


@dataclass
class EncodingFileResult:
    """Encoding detection result for a single file."""

    path: str
    encoding: str
    confidence: float


@dataclass
class EncodingResult:
    """Aggregate encoding detection results."""

    total_analyzed: int = 0
    encoding_distribution: dict[str, int] = field(default_factory=dict)
    detection_errors: int = 0
    file_results: list[EncodingFileResult] = field(default_factory=list)


def _normalize_encoding(encoding: str) -> str:
    """Normalize an encoding name to its canonical form.

    Args:
        encoding: Raw encoding name from charset-normalizer.

    Returns:
        Canonical encoding name (e.g., "utf-8", "iso-8859-1").
    """
    try:
        canonical = codecs.lookup(encoding).name
    except LookupError:
        canonical = encoding.lower().strip()
    return _DISPLAY_OVERRIDES.get(canonical, canonical)


def analyze_encodings(
    encoding_map: dict[str, tuple[str, float]],
) -> EncodingResult:
    """Aggregate encoding detection results from the text cache.

    Takes the encoding_map produced by build_text_cache() and
    aggregates it into distribution counts.

    Args:
        encoding_map: Dict of filepath -> (encoding_name, confidence).
                      Produced by build_text_cache() for plain text files only.

    Returns:
        Aggregated encoding analysis results.
    """
    result = EncodingResult()

    for path, (encoding, confidence) in encoding_map.items():
        canonical = _normalize_encoding(encoding)
        file_result = EncodingFileResult(path=path, encoding=canonical, confidence=confidence)
        result.file_results.append(file_result)
        result.encoding_distribution[canonical] = result.encoding_distribution.get(canonical, 0) + 1
        result.total_analyzed += 1

    return result
