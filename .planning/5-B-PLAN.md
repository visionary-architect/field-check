# Phase 5 - Plan B: CLI + Report Integration + Tests

## Overview
Wire the shared text cache, language detection, and encoding detection into the CLI pipeline and terminal report. Add comprehensive tests for both modules.

## Prerequisites
- Plan A complete (language.py, encoding.py, text.py cache, pii.py refactored)
- All existing tests passing

## Files to Create/Modify
- `src/field_check/cli.py` — MODIFY: Add text cache, language, encoding pipeline steps; pass cache to PII
- `src/field_check/report/__init__.py` — MODIFY: Add language_result and encoding_result parameters
- `src/field_check/report/terminal.py` — MODIFY: Add "Language & Encoding" section with two sub-tables
- `tests/test_lang_encoding.py` — NEW: Combined language + encoding tests
- `tests/conftest.py` — MODIFY: Add multi-language test fixtures

## Task Details

### Step 1: Modify cli.py — Wire Shared Text Cache + Language + Encoding

Update the pipeline in `scan()` to:

1. **Add imports** at top:
```python
from field_check.scanner.encoding import analyze_encodings
from field_check.scanner.language import analyze_languages
from field_check.scanner.text import build_text_cache
```

2. **Add shared text cache step** after the existing text extraction step (after line ~160):
```python
# Build shared text cache for PII + language + encoding
text_cache_result = None
if sample.total_sample_size > 0:
    with console.status(
        "[bold blue]Extracting text content...", spinner="dots"
    ) as status:
        def on_cache(current: int, total: int) -> None:
            status.update(
                f"[bold blue]Extracting text content... "
                f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
            )
        text_cache_result = build_text_cache(
            sample, inventory, progress_callback=on_cache
        )
```

3. **Pass text cache to PII scanner** — change the `scan_pii()` call:
```python
pii_result = scan_pii(
    sample, inventory, config,
    text_cache=text_cache_result.text_cache if text_cache_result else None,
    progress_callback=on_pii,
)
```

4. **Add language detection step** after PII:
```python
language_result = None
if text_cache_result and text_cache_result.text_cache:
    with console.status("[bold blue]Detecting languages...", spinner="dots"):
        language_result = analyze_languages(text_cache_result.text_cache)
```

5. **Add encoding detection step** after language:
```python
encoding_result = None
if text_cache_result and text_cache_result.encoding_map:
    encoding_result = analyze_encodings(text_cache_result.encoding_map)
```

6. **Pass results to generate_report()**:
```python
generate_report(
    ...,
    language_result=language_result,
    encoding_result=encoding_result,
)
```

### Step 2: Modify report/__init__.py — Add Parameters

Update `generate_report()` signature:

```python
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.language import LanguageResult

def generate_report(
    ...,
    pii_result: PIIScanResult | None = None,
    language_result: LanguageResult | None = None,  # NEW
    encoding_result: EncodingResult | None = None,   # NEW
) -> None:
```

Pass through to `render_terminal_report()`:
```python
render_terminal_report(
    ...,
    language_result=language_result,
    encoding_result=encoding_result,
)
```

### Step 3: Modify terminal.py — Add Language & Encoding Section

Add a new report section between PII Risk Indicators and Size Distribution.

**Add imports:**
```python
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.language import LanguageResult
```

**Update `render_terminal_report()` signature:**
```python
def render_terminal_report(
    ...,
    pii_result: PIIScanResult | None = None,
    language_result: LanguageResult | None = None,
    encoding_result: EncodingResult | None = None,
) -> None:
```

**Add Section 6 call** (between PII and Size Distribution):
```python
# Section 6: Language & Encoding
if language_result is not None or encoding_result is not None:
    _render_language_encoding(
        language_result, encoding_result, sample_result, console
    )
```

**Renumber existing sections** (Size → 7, Age → 8, Dir → 9, Issues → 10).

**New function `_render_language_encoding()`:**

```python
def _render_language_encoding(
    language: LanguageResult | None,
    encoding: EncodingResult | None,
    sample: SampleResult | None,
    console: Console,
) -> None:
    """Render combined Language & Encoding section with two sub-tables."""
```

**Language Distribution sub-table:**
- Title: "Language Distribution"
- Columns: Language, Count, Proportion (with CI)
- Sort by count descending
- Show top 10 languages, collapse rest into "Other"
- Use `compute_confidence_interval()` for proportions
- Total analyzed count in a summary line

**Encoding Distribution sub-table:**
- Title: "Encoding Distribution"
- Columns: Encoding, Count, %
- Sort by count descending
- Show all encodings (unlikely to be many)
- Note: "Encoding detected for plain text files only (PDF/DOCX handle encoding internally)"

### Step 4: Create tests/test_lang_encoding.py

Comprehensive tests for both language and encoding modules:

**Language detection tests (`TestLanguageDetection`):**
- `test_detect_english` — English text → "English"
- `test_detect_spanish` — Spanish text → "Spanish"
- `test_detect_french` — French text → "French"
- `test_detect_german` — German text → "German"
- `test_detect_portuguese` — Portuguese text → "Portuguese"
- `test_detect_italian` — Italian text → "Italian"
- `test_detect_dutch` — Dutch text → "Dutch"
- `test_detect_cjk` — Chinese/Japanese text → "CJK"
- `test_detect_arabic` — Arabic text → "Arabic"
- `test_detect_cyrillic` — Russian text → "Cyrillic"
- `test_detect_short_text` — Short text (< 50 chars) → "Unknown"
- `test_detect_mixed_script` — Mixed script text → "Mixed Script"

**Language analysis tests (`TestAnalyzeLanguages`):**
- `test_empty_cache` — Empty dict → zero counts
- `test_single_language` — All English → English count matches
- `test_multi_language` — Mix of EN/ES/FR → correct distribution
- `test_progress_callback` — Callback receives (current, total)

**Encoding tests (`TestEncodingAnalysis`):**
- `test_empty_map` — Empty dict → zero counts
- `test_single_encoding` — All utf-8 → {utf-8: N}
- `test_mixed_encodings` — Mix of utf-8/iso-8859-1 → correct counts
- `test_ascii_normalized` — ASCII entries normalized appropriately

**Text cache tests (`TestBuildTextCache`):**
- `test_cache_pdf` — PDF file extracted into cache
- `test_cache_plain_text` — Plain text file extracted with encoding
- `test_cache_mixed_corpus` — Mix of types → all in cache
- `test_cache_errors` — Corrupt file → error counted, not crashed

**PII with cache tests (`TestPiiWithCache`):**
- `test_pii_uses_cache` — PII scan with pre-populated cache → same results as without
- `test_pii_cache_skips_extraction` — Verify cache prevents file re-reading

### Step 5: Modify tests/conftest.py — Add Test Fixtures

Add new fixtures:

```python
@pytest.fixture
def tmp_multilang_corpus(tmp_path):
    """Create a corpus with multi-language content."""
    # English text file
    (tmp_path / "english.txt").write_text(
        "The quick brown fox jumps over the lazy dog. "
        "This is a simple English document for testing purposes.",
        encoding="utf-8",
    )
    # Spanish text file
    (tmp_path / "spanish.txt").write_text(
        "El gato está en la mesa. Los perros son grandes y fuertes. "
        "Esta es una prueba del sistema de detección de idiomas.",
        encoding="utf-8",
    )
    # French text file
    (tmp_path / "french.txt").write_text(
        "Le chat est sur la table. Les chiens sont grands et forts. "
        "Ceci est un test du système de détection de langue.",
        encoding="utf-8",
    )
    # Latin-1 encoded file
    (tmp_path / "latin1.txt").write_bytes(
        "Ménü für höfliche Gäste".encode("iso-8859-1")
    )
    return tmp_path
```

### Step 6: Lint + Full Test Suite

1. Run `uv run ruff check src/ tests/` — fix any issues
2. Run `uv run pytest --cov --cov-fail-under=80` — verify all tests pass with coverage

### Step 7: Commit

Stage and commit:
```
feat(5-B): integrate language and encoding detection into CLI and report
```

## Verification
- [ ] `uv run field-check scan ./tests/fixtures/` shows "Language & Encoding" section
- [ ] Language Distribution table shows detected languages with CIs
- [ ] Encoding Distribution table shows detected encodings
- [ ] PII scan still works correctly (using text cache)
- [ ] All existing report sections still render (regression)
- [ ] `uv run ruff check src/ tests/` — clean
- [ ] `uv run pytest --cov --cov-fail-under=80` — all pass, ≥80% coverage

## Done When
- CLI pipeline: walk → inventory → hash → corruption → sample → text extract → **text cache** → PII (with cache) → **language** → **encoding** → report
- Terminal report shows "Language & Encoding" section with language distribution + encoding distribution sub-tables
- Language distribution shows CIs (Invariant 4)
- PII scanner uses shared text cache (no duplicate file reads)
- All tests pass with ≥80% coverage
- No lint errors

## Notes
- Language detection runs in the main process (pure CPU, no I/O needed) — no ProcessPoolExecutor required
- Encoding detection is just aggregation of data from text cache — instant, no I/O
- The text cache extraction step (from Plan A) is the only step that does file I/O, and it uses ProcessPoolExecutor for crash isolation (Invariant 5)
- Report section order: Types → Duplicates → Health → Content Analysis → PII → **Language & Encoding** → Size → Age → Directory → Issues
- Encoding note in report: displayed only for plain text files (PDF/DOCX handle encoding internally)
