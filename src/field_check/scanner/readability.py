"""Readability scoring using textstat (optional)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Minimum text length worth scoring (short strings give unreliable results)
_MIN_TEXT_LENGTH = 200

# Below this Flesch Reading Ease score, text is likely OCR garbage or legalese
LOW_QUALITY_THRESHOLD = 30.0


@dataclass
class ReadabilityScore:
    """Readability score for a single file."""

    path: str
    flesch_reading_ease: float
    is_low_quality: bool


@dataclass
class ReadabilityResult:
    """Results from readability analysis."""

    total_checked: int = 0
    low_quality_count: int = 0
    avg_flesch_score: float = 0.0
    scores: list[ReadabilityScore] = field(default_factory=list)


def analyze_readability(text_cache: dict[str, str]) -> ReadabilityResult:
    """Analyze readability of cached text using textstat.

    Computes Flesch Reading Ease scores. Files scoring below
    LOW_QUALITY_THRESHOLD are flagged as low quality (likely OCR
    garbage, binary data misidentified as text, or dense legalese).

    Args:
        text_cache: Dict of filepath -> extracted text content.

    Returns:
        ReadabilityResult with per-file scores and aggregates.
    """
    try:
        import textstat
    except ImportError:
        logger.debug("textstat not installed — skipping readability analysis")
        return ReadabilityResult()

    result = ReadabilityResult()
    total_score = 0.0

    for path, text in text_cache.items():
        if len(text) < _MIN_TEXT_LENGTH:
            continue

        result.total_checked += 1

        try:
            score = textstat.flesch_reading_ease(text)
            is_low = score < LOW_QUALITY_THRESHOLD
            if is_low:
                result.low_quality_count += 1

            result.scores.append(ReadabilityScore(
                path=path,
                flesch_reading_ease=round(score, 1),
                is_low_quality=is_low,
            ))
            total_score += score
        except Exception:
            logger.debug("Readability scoring failed for %s", path)

    if result.total_checked > 0:
        result.avg_flesch_score = round(total_score / result.total_checked, 1)

    return result
