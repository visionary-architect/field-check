"""Language detection via Unicode script ranges and stop-word profiles."""

from __future__ import annotations

import bisect
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Minimum characters required for reliable language detection
# Lower threshold works for CJK/Arabic/Cyrillic (1 char ≈ 1 word)
MIN_CHARS_FOR_DETECTION = 20

# Minimum stop-word matches to declare a language (avoid false positives)
MIN_STOPWORD_MATCHES = 3

# Unicode script ranges: script name -> list of (start, end) codepoint ranges
UNICODE_SCRIPTS: dict[str, list[tuple[int, int]]] = {
    "Latin": [
        (0x0041, 0x024F),    # Basic Latin + Latin Extended-A/B
        (0x1E00, 0x1EFF),    # Latin Extended Additional
        (0x2C60, 0x2C7F),    # Latin Extended-C
        (0xA720, 0xA7FF),    # Latin Extended-D
    ],
    "CJK": [
        (0x4E00, 0x9FFF),    # CJK Unified Ideographs
        (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
        (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
        (0x20000, 0x2A6DF),  # CJK Unified Ideographs Extension B
    ],
    "Japanese Kana": [
        (0x3040, 0x309F),    # Hiragana
        (0x30A0, 0x30FF),    # Katakana
        (0x31F0, 0x31FF),    # Katakana Phonetic Extensions
    ],
    "Arabic": [
        (0x0600, 0x06FF),    # Arabic
        (0x0750, 0x077F),    # Arabic Supplement
        (0xFB50, 0xFDFF),    # Arabic Presentation Forms-A
        (0xFE70, 0xFEFF),    # Arabic Presentation Forms-B
    ],
    "Cyrillic": [
        (0x0400, 0x04FF),    # Cyrillic
        (0x0500, 0x052F),    # Cyrillic Supplement
        (0x2DE0, 0x2DFF),    # Cyrillic Extended-A
        (0xA640, 0xA69F),    # Cyrillic Extended-B
    ],
    "Devanagari": [
        (0x0900, 0x097F),    # Devanagari
        (0xA8E0, 0xA8FF),    # Devanagari Extended
    ],
    "Greek": [
        (0x0370, 0x03FF),    # Greek and Coptic
        (0x1F00, 0x1FFF),    # Greek Extended
    ],
    "Hangul": [
        (0xAC00, 0xD7AF),   # Hangul Syllables
        (0x1100, 0x11FF),    # Hangul Jamo
        (0x3130, 0x318F),    # Hangul Compatibility Jamo
    ],
    "Thai": [
        (0x0E00, 0x0E7F),   # Thai
    ],
    "Hebrew": [
        (0x0590, 0x05FF),   # Hebrew
        (0xFB1D, 0xFB4F),   # Hebrew Presentation Forms
    ],
}

# Build a flat sorted lookup table for O(log n) codepoint classification.
# Each entry is (range_start, range_end, script_name), sorted by start.
_SCRIPT_TABLE: list[tuple[int, int, str]] = sorted(
    (start, end, script)
    for script, ranges in UNICODE_SCRIPTS.items()
    for start, end in ranges
)
_SCRIPT_STARTS: list[int] = [entry[0] for entry in _SCRIPT_TABLE]

# 7 core Latin-script stop-word profiles for language disambiguation
STOP_WORDS: dict[str, set[str]] = {
    "English": {
        "the", "and", "is", "in", "to", "of", "a", "that", "it", "for",
        "was", "on", "are", "with", "as", "at", "be", "this", "have", "from",
        "or", "an", "by", "not", "but",
    },
    "Spanish": {
        "de", "la", "que", "el", "en", "y", "los", "del", "se", "las",
        "por", "un", "para", "con", "no", "una", "su", "al", "es", "lo",
    },
    "French": {
        "le", "la", "de", "et", "les", "des", "en", "un", "une", "du",
        "est", "que", "pour", "dans", "ce", "pas", "sur", "ne", "qui", "au",
    },
    "German": {
        "der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich",
        "des", "auf", "ist", "im", "dem", "nicht", "ein", "eine", "auch",
    },
    "Portuguese": {
        "de", "a", "o", "que", "e", "do", "da", "em", "um", "para",
        "com", "os", "no", "se", "na", "por", "mais", "as", "dos",
    },
    "Italian": {
        "di", "che", "il", "la", "per", "un", "non", "si", "lo", "le",
        "con", "da", "una", "del", "sono", "dei", "al", "ha",
    },
    "Dutch": {
        "de", "het", "een", "van", "en", "in", "is", "dat", "op", "te",
        "voor", "met", "zijn", "er", "aan", "ook", "niet", "maar", "om",
    },
}

# Pre-compile word tokenizer
_WORD_PATTERN = re.compile(r"[a-zA-ZÀ-ÿ]+")


@dataclass
class LanguageFileResult:
    """Language detection result for a single file."""

    path: str
    language: str
    script: str


@dataclass
class LanguageResult:
    """Aggregate language detection results."""

    total_analyzed: int = 0
    language_distribution: dict[str, int] = field(default_factory=dict)
    script_distribution: dict[str, int] = field(default_factory=dict)
    detection_errors: int = 0
    file_results: list[LanguageFileResult] = field(default_factory=list)


def _classify_script(codepoint: int) -> str | None:
    """Return the script name for a Unicode codepoint, or None if unclassified.

    Uses bisect on a pre-sorted table for O(log n) lookup.
    """
    idx = bisect.bisect_right(_SCRIPT_STARTS, codepoint) - 1
    if idx >= 0:
        start, end, script = _SCRIPT_TABLE[idx]
        if start <= codepoint <= end:
            return script
    return None


def _get_script_distribution(text: str) -> dict[str, int]:
    """Count characters per Unicode script in the text.

    Skips whitespace, digits, and punctuation (common/neutral characters).
    """
    dist: dict[str, int] = {}
    for char in text:
        cp = ord(char)
        # Skip ASCII control, whitespace, digits, basic punctuation
        if cp < 0x0041:
            continue
        # Skip general punctuation and symbols
        if cp in range(0x005B, 0x0061) or cp in range(0x007B, 0x00C0):
            continue
        script = _classify_script(cp)
        if script:
            dist[script] = dist.get(script, 0) + 1
    return dist


def _detect_latin_language(text: str) -> str:
    """Disambiguate Latin-script languages using stop-word matching.

    Tokenizes text into lowercase words, counts matches against each
    stop-word profile, returns language with most matches.

    Returns:
        Language name or "Latin (Unknown)" if no profile matches well.
    """
    words = [w.lower() for w in _WORD_PATTERN.findall(text)]
    if not words:
        return "Latin (Unknown)"

    scores: dict[str, int] = {}
    for lang, stopwords in STOP_WORDS.items():
        count = sum(1 for w in words if w in stopwords)
        scores[lang] = count

    best_lang = max(scores, key=lambda k: scores[k])
    if scores[best_lang] < MIN_STOPWORD_MATCHES:
        return "Latin (Unknown)"

    return best_lang


def detect_language(
    text: str,
    min_chars: int = MIN_CHARS_FOR_DETECTION,
    _script_dist: dict[str, int] | None = None,
) -> str:
    """Detect the primary language/script of a text.

    Algorithm:
    1. If text too short, return "Unknown"
    2. Count Unicode script distribution
    3. Find dominant script (>50% of classified chars)
    4. If Latin: run stop-word disambiguation
    5. If non-Latin: return script name
    6. If no dominant script: return "Mixed Script"

    Args:
        text: The text content to analyze.
        min_chars: Minimum character count for detection.
        _script_dist: Pre-computed script distribution (internal, avoids
            recomputation when caller already has it).

    Returns:
        Detected language name (e.g., "English", "CJK", "Arabic").
    """
    # Strip and check minimum length
    text = text.strip()
    if len(text) < min_chars:
        return "Unknown"

    # Get script distribution
    script_dist = _script_dist if _script_dist is not None else _get_script_distribution(text)
    if not script_dist:
        return "Unknown"

    total_classified = sum(script_dist.values())
    if total_classified == 0:
        return "Unknown"

    # Find dominant script
    dominant_script = max(script_dist, key=lambda k: script_dist[k])
    dominant_fraction = script_dist[dominant_script] / total_classified

    if dominant_fraction < 0.5:
        return "Mixed Script"

    # For Latin script, disambiguate with stop-words
    if dominant_script == "Latin":
        return _detect_latin_language(text)

    # For Japanese: check if CJK + Kana are both present
    if dominant_script in ("CJK", "Japanese Kana"):
        has_cjk = script_dist.get("CJK", 0) > 0
        has_kana = script_dist.get("Japanese Kana", 0) > 0
        if has_cjk and has_kana:
            return "Japanese"
        if dominant_script == "Japanese Kana":
            return "Japanese"
        # Pure CJK could be Chinese, Japanese, or Korean
        # If Hangul is present, it's Korean
        if script_dist.get("Hangul", 0) > 0:
            return "Korean"
        return "CJK"

    if dominant_script == "Hangul":
        return "Korean"

    return dominant_script


def analyze_languages(
    text_cache: dict[str, str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> LanguageResult:
    """Analyze languages across all cached texts.

    Pure function — no file I/O, processes pre-extracted text.
    Runs in main process (no ProcessPoolExecutor needed).

    Args:
        text_cache: Dict mapping file path to extracted text content.
        progress_callback: Called with (current, total) for progress display.

    Returns:
        Aggregated language analysis results.
    """
    result = LanguageResult()
    total = len(text_cache)

    for idx, (path, text) in enumerate(text_cache.items(), 1):
        try:
            # Compute script distribution once, reuse for both detection and reporting
            script_dist = _get_script_distribution(text.strip())
            language = detect_language(text, _script_dist=script_dist)
            dominant_script = (
                max(script_dist, key=lambda k: script_dist[k])
                if script_dist
                else "Unknown"
            )

            file_result = LanguageFileResult(
                path=path, language=language, script=dominant_script
            )
            result.file_results.append(file_result)
            result.language_distribution[language] = (
                result.language_distribution.get(language, 0) + 1
            )
            result.script_distribution[dominant_script] = (
                result.script_distribution.get(dominant_script, 0) + 1
            )
        except Exception:
            logger.warning("Language detection failed for %s", path, exc_info=True)
            result.detection_errors += 1

        result.total_analyzed += 1

        if progress_callback is not None:
            progress_callback(idx, total)

    return result
