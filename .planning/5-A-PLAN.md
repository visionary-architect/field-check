# Phase 5 - Plan A: Language + Encoding Scanner Modules + Shared Text Cache

## Overview
Create the language detection module (Unicode scripts + 7 stop-word profiles), encoding detection module, shared text cache extraction in text.py, and refactor PII scanner to accept pre-extracted text.

## Prerequisites
- Phase 4 complete (PII scanner, text extraction pipeline working)
- All 107 tests passing

## Files to Create/Modify
- `src/field_check/scanner/language.py` — NEW: Language detection via Unicode script ranges + stop-word profiles
- `src/field_check/scanner/encoding.py` — NEW: Encoding result aggregation dataclass
- `src/field_check/scanner/text.py` — MODIFY: Add `build_text_cache()` + plain text extraction support
- `src/field_check/scanner/pii.py` — MODIFY: Accept `text_cache` parameter, skip re-reading cached files

## Task Details

### Step 1: Create language.py — Unicode Script Detection + Stop-Word Profiles

Create `src/field_check/scanner/language.py` with:

**Unicode script ranges** — dict mapping script name to list of (start, end) codepoint ranges:
- Latin: U+0041–U+024F, U+1E00–U+1EFF, U+2C60–U+2C7F
- CJK: U+4E00–U+9FFF, U+3400–U+4DBF, U+3000–U+303F, U+F900–U+FAFF
- Arabic: U+0600–U+06FF, U+0750–U+077F, U+FB50–U+FDFF, U+FE70–U+FEFF
- Cyrillic: U+0400–U+04FF, U+0500–U+052F
- Devanagari: U+0900–U+097F
- Greek: U+0370–U+03FF
- Hangul: U+AC00–U+D7AF, U+1100–U+11FF, U+3130–U+318F
- Thai: U+0E00–U+0E7F
- Hebrew: U+0590–U+05FF
- Japanese Kana: U+3040–U+309F, U+30A0–U+30FF (separate from CJK for better detection)

**7 stop-word profiles** — dict mapping language name to set of 20-30 common stop words:
- English: the, and, is, in, to, of, a, that, it, for, was, on, are, with, as, at, be, this, have, from, or, an, by, not, but
- Spanish: de, la, que, el, en, y, los, del, se, las, por, un, para, con, no, una, su, al, es, lo, más, pero
- French: le, la, de, et, les, des, en, un, une, du, est, que, pour, dans, ce, pas, sur, ne, qui, au, sont, il
- German: der, die, und, in, den, von, zu, das, mit, sich, des, auf, für, ist, im, dem, nicht, ein, eine, auch
- Portuguese: de, a, o, que, e, do, da, em, um, para, com, não, uma, os, no, se, na, por, mais, as, dos
- Italian: di, che, il, la, per, un, in, non, è, si, lo, le, con, da, una, del, sono, dei, al, ha, più
- Dutch: de, het, een, van, en, in, is, dat, op, te, voor, met, zijn, er, aan, ook, niet, maar, om, als

**Functions:**

```python
def _classify_script(char: str) -> str | None:
    """Return the script name for a character, or None if common/unknown."""

def _get_script_distribution(text: str) -> dict[str, int]:
    """Count characters per Unicode script in the text."""

def _detect_latin_language(text: str) -> str:
    """Disambiguate Latin-script languages using stop-word matching.

    Tokenize text into lowercase words, count matches against each
    stop-word profile, return language with most matches.
    Falls back to 'Latin (Unknown)' if no profile reaches minimum threshold.
    """

def detect_language(text: str, min_chars: int = 50) -> str:
    """Detect the primary language/script of a text.

    1. If text too short (< min_chars), return 'Unknown'
    2. Count Unicode script distribution
    3. Find dominant script (>50% of classified chars)
    4. If dominant script is Latin: run stop-word disambiguation
    5. If non-Latin: return script name (e.g., 'CJK', 'Arabic', 'Cyrillic')
    6. If no dominant script: return 'Mixed Script'
    """
```

**Dataclasses:**

```python
@dataclass
class LanguageFileResult:
    path: str
    language: str
    script: str  # e.g., 'Latin', 'CJK', 'Arabic'

@dataclass
class LanguageResult:
    total_analyzed: int = 0
    language_distribution: dict[str, int] = field(default_factory=dict)
    script_distribution: dict[str, int] = field(default_factory=dict)
    detection_errors: int = 0
    file_results: list[LanguageFileResult] = field(default_factory=list)
```

**Main function:**

```python
def analyze_languages(
    text_cache: dict[str, str],
    progress_callback: Callable[[int, int], None] | None = None,
) -> LanguageResult:
    """Analyze languages across all cached texts.

    Pure function — no file I/O, just processes pre-extracted text.
    Runs in main process (no ProcessPoolExecutor needed since no I/O).
    """
```

### Step 2: Create encoding.py — Encoding Result Aggregation

Create `src/field_check/scanner/encoding.py` with:

**Dataclasses:**

```python
@dataclass
class EncodingFileResult:
    path: str
    encoding: str
    confidence: float

@dataclass
class EncodingResult:
    total_analyzed: int = 0
    encoding_distribution: dict[str, int] = field(default_factory=dict)  # encoding -> file count
    detection_errors: int = 0
    file_results: list[EncodingFileResult] = field(default_factory=list)
```

**Main function:**

```python
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
```

Normalize encoding names to canonical form (e.g., "utf-8", "ascii", "iso-8859-1", "windows-1252"). Group similar encodings (ascii is a subset of utf-8, so count ascii files as utf-8).

### Step 3: Modify text.py — Add Shared Text Cache Builder

Add these to `src/field_check/scanner/text.py`:

**New constants:**

```python
# MIME types for plain text content extraction
PLAIN_TEXT_MIMES: set[str] = {
    "text/plain", "text/csv", "text/json", "text/xml",
    "application/json", "application/xml",
}

# Combined set for text cache extraction
CACHE_EXTRACTABLE_MIMES: set[str] = EXTRACTABLE_MIMES | PLAIN_TEXT_MIMES

# Max bytes to read from plain text files
_MAX_TEXT_READ = 1_000_000
```

**New dataclass:**

```python
@dataclass
class TextCacheResult:
    """Result of shared text cache extraction."""
    text_cache: dict[str, str] = field(default_factory=dict)  # path -> text
    encoding_map: dict[str, tuple[str, float]] = field(default_factory=dict)  # path -> (encoding, confidence)
    total_extracted: int = 0
    extraction_errors: int = 0
```

**New worker function** (top-level for pickling):

```python
def _extract_text_for_cache(
    filepath: str, mime_type: str
) -> tuple[str, str | None, float, str | None]:
    """Worker function to extract text content from any supported file.

    Returns: (text, encoding_name, encoding_confidence, error)
    - For PDF: uses pdfplumber, encoding is None
    - For DOCX: uses python-docx, encoding is None
    - For plain text: uses charset-normalizer, encoding is detected
    """
```

This function reuses the same extraction logic as `_extract_text_for_pii()` in pii.py but also returns encoding info for plain text files.

**New main function:**

```python
def build_text_cache(
    sample: SampleResult,
    inventory: InventoryResult,
    max_workers: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> TextCacheResult:
    """Build shared text cache for downstream analysis (PII, language, encoding).

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
```

The implementation follows the same ProcessPoolExecutor pattern as `extract_text()` and `scan_pii()`.

### Step 4: Modify pii.py — Accept Pre-Extracted Text Cache

Modify `scan_pii()` to accept an optional `text_cache` parameter:

```python
def scan_pii(
    sample: SampleResult,
    inventory: InventoryResult,
    config: FieldCheckConfig,
    text_cache: dict[str, str] | None = None,  # NEW parameter
    max_workers: int | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> PIIScanResult:
```

When `text_cache` is provided:
1. For files found in the cache: run PII regex matching directly in the main process (pure CPU, no I/O needed). Call `_scan_single_file()` with a modified approach — create a new helper `_scan_text_for_pii()` that takes a text string instead of extracting from file.
2. For files NOT in the cache: fall back to existing ProcessPoolExecutor behavior.
3. This avoids re-reading files that were already extracted for the shared cache.

Add new helper function:

```python
def _scan_text_for_pii(
    filepath: str,
    text: str,
    compiled_patterns: list[tuple[str, str, re.Pattern[str], str | None]],
    show_samples: bool,
) -> PIIFileResult:
    """Scan pre-extracted text for PII patterns (no file I/O)."""
```

This is similar to `_scan_single_file()` but takes text directly instead of calling `_extract_text_for_pii()`.

Keep `_extract_text_for_pii()` for backward compatibility (used when no cache is provided).

## Verification
- [ ] `uv run python -c "from field_check.scanner.language import detect_language; print(detect_language('The quick brown fox jumps over the lazy dog'))"` → "English"
- [ ] `uv run python -c "from field_check.scanner.language import detect_language; print(detect_language('Le chat est sur la table'))"` → "French"
- [ ] `uv run python -c "from field_check.scanner.encoding import analyze_encodings; r = analyze_encodings({'a.txt': ('utf-8', 0.99)}); print(r.encoding_distribution)"` → `{'utf-8': 1}`
- [ ] `uv run ruff check src/field_check/scanner/language.py src/field_check/scanner/encoding.py`
- [ ] Existing tests still pass: `uv run pytest tests/ -x`

## Done When
- language.py can detect English, Spanish, French, German, Portuguese, Italian, Dutch via stop-words
- language.py identifies CJK, Arabic, Cyrillic, Devanagari, Greek, Hangul, Thai, Hebrew via Unicode scripts
- encoding.py aggregates encoding results from text cache
- text.py has `build_text_cache()` that extracts text + encoding from all supported file types
- pii.py accepts `text_cache` and skips re-reading cached files
- All existing tests pass

## Notes
- Stop-word profiles should have 20-30 words each — enough for reliable detection, small enough to embed as constants
- `_classify_script()` should use binary search or range check on codepoints for performance
- encoding.py is deliberately thin — it just aggregates the encoding data captured during text cache extraction
- The `_extract_text_for_cache()` worker in text.py essentially replaces `_extract_text_for_pii()` in pii.py — same logic but also returns encoding for plain text files
- Plain text files have `_MAX_TEXT_READ = 1_000_000` bytes limit (same as PII scanner)
- ProcessPoolExecutor in `build_text_cache()` provides crash isolation (Invariant 5)
