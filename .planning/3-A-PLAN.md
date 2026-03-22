# Phase 3 - Plan A: Sampling Framework + Text Extraction Pipeline

## Overview
Create the stratified sampling framework, confidence interval calculations, and the single-pass text extraction pipeline with ProcessPoolExecutor crash isolation. This is the core engine for all content-level analyses.

## Prerequisites
- Phase 2 complete (walk, inventory, dedup, corruption all working)
- pdfplumber and python-docx in pyproject.toml dependencies (already added)

## Files to Create/Modify
- `src/field_check/config.py` - Add sampling_rate, sampling_min_per_type fields
- `src/field_check/scanner/inventory.py` - Add per-file type mapping to InventoryResult
- `src/field_check/scanner/sampling.py` - NEW: Stratified sampling + confidence intervals
- `src/field_check/scanner/text.py` - NEW: ProcessPoolExecutor text extraction pipeline

## Task Details

### Step 1: Update FieldCheckConfig with Sampling Fields

In `src/field_check/config.py`:
- Add `sampling_rate: float = 0.10` to `FieldCheckConfig`
- Add `sampling_min_per_type: int = 30` to `FieldCheckConfig`
- Update `load_config()` to parse `sampling.rate` and `sampling.min_per_type` from YAML config

The YAML structure follows the spec:
```yaml
sampling:
  rate: 0.10
  min_per_type: 30
```

### Step 2: Add Per-File Type Mapping to InventoryResult

In `src/field_check/scanner/inventory.py`:
- Add `file_types: dict[Path, str]` field to `InventoryResult` dataclass
- In `analyze_inventory()`, store `file_types[entry.path] = mime` during the detection loop

This is a small additive change. The per-file mapping is needed for stratified sampling (to know which files are which type) and for text extraction (to dispatch to the right extractor).

### Step 3: Create Sampling Module

Create `src/field_check/scanner/sampling.py` with:

**Dataclasses:**
```python
@dataclass
class ConfidenceInterval:
    """Confidence interval for a sampled proportion."""
    point_estimate: float      # p-hat
    lower: float               # lower bound
    upper: float               # upper bound
    confidence_level: float    # e.g. 0.95
    sample_size: int
    population_size: int

@dataclass
class SampleResult:
    """Result of stratified sampling."""
    selected_files: list[FileEntry]
    per_type_sample: dict[str, list[FileEntry]]    # MIME -> sampled files
    per_type_population: dict[str, int]             # MIME -> total count
    total_sample_size: int
    total_population_size: int
    sampling_rate: float
    is_census: bool            # True if all files selected (rate >= 1.0)
```

**Functions:**
- `select_sample(walk_result, inventory, config) -> SampleResult`
  - Group files by MIME type using `inventory.file_types`
  - For each type: select `max(ceil(count * rate), min(min_per_type, count))` files
  - Use `random.sample()` for selection within each type
  - If computed sample >= population for a type, take all (census)
  - Track per-type sample sizes and population sizes

- `compute_confidence_interval(successes, sample_size, population_size, confidence=0.95) -> ConfidenceInterval`
  - Use Wilson score interval (robust for small samples and edge proportions)
  - Apply finite population correction factor: `sqrt((N - n) / (N - 1))`
  - Return ConfidenceInterval with bounds clamped to [0, 1]
  - If census (sample_size >= population_size), return exact values with zero margin

- `format_ci(ci: ConfidenceInterval) -> str`
  - Format as "XX.X% (CI: XX.X% -- XX.X%, n=N)" for report display
  - If census, format as "XX.X% (exact, N=N)"

**Implementation notes:**
- Wilson score interval formula:
  ```
  center = (p + z²/2n) / (1 + z²/n)
  margin = z * sqrt((p(1-p) + z²/4n) / n) / (1 + z²/n)
  ```
  Then apply FPC to margin.
- z = 1.96 for 95% confidence
- Use `math` stdlib only (no scipy dependency)

### Step 4: Create Text Extraction Module

Create `src/field_check/scanner/text.py` with:

**Constants:**
```python
EXTRACTABLE_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

METADATA_FIELDS = ["title", "author", "creation_date"]

# Image-heavy classification thresholds (from 3-CONTEXT.md)
CHARS_PER_PAGE_IMAGE_HEAVY = 100    # < 100 = image-heavy
CHARS_PER_PAGE_TEXT_HEAVY = 500     # > 500 = text-heavy
TEXT_SIZE_RATIO_IMAGE_HEAVY = 0.05  # < 5% = image-heavy signal

CLASSIFICATION_TEXT_HEAVY = "text_heavy"
CLASSIFICATION_IMAGE_HEAVY = "image_heavy"
CLASSIFICATION_MIXED = "mixed"

DEFAULT_TIMEOUT = 30.0
MAX_WORKERS = 4
```

**Dataclasses:**
```python
@dataclass
class TextResult:
    """Extraction result for a single file."""
    path: Path
    text_length: int = 0
    page_count: int = 0
    chars_per_page: float = 0.0
    text_size_ratio: float = 0.0
    is_scanned: bool = False       # All pages have zero chars
    is_mixed_scan: bool = False    # Some pages scanned, some native
    classification: str = ""       # text_heavy / image_heavy / mixed
    metadata: dict[str, str | None] = field(default_factory=dict)
    error: str | None = None

@dataclass
class TextExtractionResult:
    """Aggregate results from text extraction across sampled files."""
    total_processed: int = 0
    extraction_errors: int = 0
    timeout_errors: int = 0
    # Scanned detection
    scanned_count: int = 0
    native_count: int = 0
    mixed_scan_count: int = 0
    # Content classification
    text_heavy_count: int = 0
    image_heavy_count: int = 0
    mixed_content_count: int = 0
    # Metadata completeness: field_name -> count of files having non-empty value
    metadata_field_counts: dict[str, int] = field(default_factory=dict)
    metadata_total_checked: int = 0
    # Per-file results
    file_results: list[TextResult] = field(default_factory=list)
```

**Worker functions (must be top-level for ProcessPoolExecutor pickling):**

- `_extract_pdf(filepath: str) -> TextResult`
  - Single pass per 3-CONTEXT.md decision:
  - Open with `pdfplumber.open(filepath)`
  - Iterate pages:
    - Count `len(page.chars)` per page
    - Extract text via `page.extract_text()` (accumulate total text length)
    - Track pages with zero chars (scanned pages)
  - Extract metadata: `pdf.metadata` dict
    - Map 'Title' -> 'title', 'Author' -> 'author', 'CreationDate' -> 'creation_date'
  - Compute chars_per_page = total_chars / page_count
  - Compute text_size_ratio = len(text.encode('utf-8')) / file_size
  - Classify scanned/native:
    - If ALL pages have zero chars -> is_scanned = True
    - If SOME pages have zero chars -> is_mixed_scan = True
    - Else -> native
  - Classify content:
    - chars_per_page < 100 -> image_heavy
    - chars_per_page > 500 -> text_heavy
    - Between -> mixed
    - Secondary: if text_size_ratio < 0.05, reinforce image_heavy signal
  - Wrap in try/except, return TextResult with error on failure

- `_extract_docx(filepath: str) -> TextResult`
  - Open with `docx.Document(filepath)`
  - Extract text from all paragraphs: `"\n".join(p.text for p in doc.paragraphs)`
  - Extract metadata from `doc.core_properties`:
    - `.title` -> 'title'
    - `.author` -> 'author'
    - `.created` -> 'creation_date' (datetime to ISO string)
  - page_count = 0 (DOCX doesn't have reliable page count without rendering)
  - chars_per_page = 0 (not applicable)
  - text_size_ratio = text_bytes / file_size
  - is_scanned = False (DOCX is never scanned)
  - classification = text_heavy (DOCX is always text-based)
  - Wrap in try/except

- `_extract_single(filepath: str, mime_type: str) -> TextResult`
  - Dispatch to `_extract_pdf` or `_extract_docx` based on mime_type
  - Return error TextResult for unsupported types

**Main extraction function:**

- `extract_text(sample, inventory, max_workers=None, timeout=30.0, progress_callback=None) -> TextExtractionResult`
  - Filter sample.selected_files to only EXTRACTABLE_MIMES using inventory.file_types
  - Use `ProcessPoolExecutor(max_workers=max_workers or min(MAX_WORKERS, cpu_count()))`
  - Submit each file with `pool.submit(_extract_single, str(path), mime)`
  - Collect results with `as_completed()`:
    - `future.result(timeout=timeout)` — catch TimeoutError, Exception
    - Call progress_callback with (current, total)
  - Aggregate into TextExtractionResult:
    - Count scanned/native/mixed_scan
    - Count text_heavy/image_heavy/mixed_content
    - Count metadata completeness per field
  - Return aggregated result

**Important design decisions:**
- Worker functions accept `str` not `Path` (for cross-process pickling reliability)
- Worker functions return `TextResult` dataclass (pickle-safe, module-level)
- `pdfplumber` and `python-docx` are imported inside worker functions to avoid import in main process
- Timeout in `future.result()` means "stop waiting" — the worker may keep running but gets cleaned up on pool shutdown
- If ALL sampled files of extractable types have been selected (census for a type), note it for confidence interval calculation

### Step 5: Run Existing Tests

Run `uv run pytest --cov` to verify nothing is broken by the inventory.py and config.py changes.

## Verification
- [ ] `uv run pytest tests/test_config.py -v` passes with new sampling fields
- [ ] `uv run pytest tests/test_inventory.py -v` passes with file_types field
- [ ] `uv run ruff check src/field_check/scanner/sampling.py src/field_check/scanner/text.py`
- [ ] `uv run pytest --cov` — all existing tests pass, coverage >= 80%
- [ ] Manual: `python -c "from field_check.scanner.sampling import select_sample, compute_confidence_interval"` imports work
- [ ] Manual: `python -c "from field_check.scanner.text import extract_text"` imports work

## Done When
- FieldCheckConfig has sampling_rate and sampling_min_per_type with YAML loading
- InventoryResult stores per-file MIME type mapping
- Sampling module selects stratified samples with configurable rate and minimum
- Confidence interval calculation with Wilson score + FPC works correctly
- Text extraction pipeline handles PDF (pdfplumber) and DOCX (python-docx)
- Single-pass extraction per file (text + metadata + scanned + classification)
- ProcessPoolExecutor provides crash isolation with per-file timeout
- All existing tests pass

## Notes
- Worker functions must be top-level (not nested/lambda) for ProcessPoolExecutor
- pdfplumber import is heavy (~15MB) — import only inside worker functions
- The `timeout` in `future.result(timeout=)` doesn't kill the worker — it just stops waiting. This is acceptable for a CLI tool that exits after the scan.
- DOCX has no reliable page count without rendering — report page_count=0 for DOCX
- For files that are NOT PDF/DOCX in the sample, text extraction skips them (they'll be used by future phases like PII, language detection on plain text)
