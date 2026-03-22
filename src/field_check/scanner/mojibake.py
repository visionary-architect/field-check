"""Mojibake (encoding damage) detection using ftfy."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

try:
    import ftfy

    _HAS_FTFY = True
except ImportError:
    _HAS_FTFY = False

logger = logging.getLogger(__name__)

# Minimum text length worth checking for mojibake
_MIN_TEXT_LENGTH = 20

# Maximum text length to pass to ftfy (avoid slow processing on huge texts)
_MAX_TEXT_LENGTH = 50_000


@dataclass
class MojibakeResult:
    """Results from mojibake (encoding damage) detection."""

    total_checked: int = 0
    files_with_mojibake: int = 0
    mojibake_files: list[str] = field(default_factory=list)


def detect_mojibake(text_cache: dict[str, str]) -> MojibakeResult:
    """Detect encoding damage (mojibake) in cached text.

    Uses ftfy's fix_and_explain() to identify text that contains
    encoding errors (e.g., UTF-8 decoded as latin-1).

    Args:
        text_cache: Dict of filepath -> extracted text content.

    Returns:
        MojibakeResult with counts and affected file paths.
    """
    result = MojibakeResult()

    if not _HAS_FTFY:
        logger.debug(
            "ftfy not installed — skipping mojibake detection. "
            "Install with: pip install ftfy"
        )
        return result

    for path, text in text_cache.items():
        if len(text) < _MIN_TEXT_LENGTH:
            continue

        result.total_checked += 1

        try:
            _fixed, explanations = ftfy.fix_and_explain(text[:_MAX_TEXT_LENGTH])
            if explanations:
                result.files_with_mojibake += 1
                result.mojibake_files.append(path)
        except Exception:
            logger.debug("Mojibake check failed for %s", path)

    return result
