# Phase 3 - Plan B: CLI + Report Integration + Tests

## Overview
Wire the sampling framework and text extraction pipeline into the CLI scan command, add terminal report sections for text analysis results (scanned PDF detection, image-heavy classification, metadata completeness), and create comprehensive test suites.

## Prerequisites
- Plan 3-A complete (sampling.py, text.py, config.py, inventory.py changes)

## Files to Create/Modify
- `src/field_check/cli.py` - Add --sampling-rate flag, wire sampling + extraction
- `src/field_check/report/__init__.py` - Accept text extraction results
- `src/field_check/report/terminal.py` - Add text analysis report sections
- `tests/conftest.py` - Add PDF/DOCX fixture helpers
- `tests/test_sampling.py` - NEW: Sampling + confidence interval tests
- `tests/test_text.py` - NEW: Text extraction pipeline tests

## Task Details

### Step 1: Update CLI Scan Command

In `src/field_check/cli.py`:

Add new CLI option:
```python
@click.option(
    "--sampling-rate", type=float, default=None,
    help="Sampling rate for content analysis (0.0-1.0, default: 0.10).",
)
```

Add to scan function parameters: `sampling_rate: float | None`

After corruption check, add:
```python
# Override sampling rate from CLI if provided
if sampling_rate is not None:
    config.sampling_rate = sampling_rate

# Select sample for content analysis
with console.status("[bold blue]Selecting sample...", spinner="dots"):
    sample = select_sample(walk_result, inventory, config)

# Extract text from sampled PDF/DOCX files
if sample.total_sample_size > 0:
    with console.status(
        "[bold blue]Extracting text...", spinner="dots"
    ) as status:
        def on_extract(current: int, total: int) -> None:
            status.update(
                f"[bold blue]Extracting text... "
                f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
            )

        text_result = extract_text(
            sample, inventory, progress_callback=on_extract
        )
else:
    text_result = None
```

Add imports:
```python
from field_check.scanner.sampling import select_sample
from field_check.scanner.text import extract_text
```

Pass `sample_result=sample` and `text_result=text_result` to `generate_report()`.

### Step 2: Update Report Dispatcher

In `src/field_check/report/__init__.py`:

Add imports:
```python
from field_check.scanner.sampling import SampleResult
from field_check.scanner.text import TextExtractionResult
```

Add parameters to `generate_report()`:
```python
def generate_report(
    ...,
    sample_result: SampleResult | None = None,
    text_result: TextExtractionResult | None = None,
) -> None:
```

Pass through to `render_terminal_report()`.

### Step 3: Add Terminal Report Sections

In `src/field_check/report/terminal.py`:

Add imports:
```python
from field_check.scanner.sampling import (
    SampleResult, compute_confidence_interval, format_ci,
)
from field_check.scanner.text import TextExtractionResult
```

Update `render_terminal_report()` signature to accept `sample_result` and `text_result`.

Add three new report sections after the File Health section:

**Section: Document Content Analysis**
`_render_text_analysis(text_result, sample_result, console)`

Summary table:
| Metric | Value |
|--------|-------|
| Files analyzed | N (of M total) |
| Sampling rate | X% |
| Extraction errors | N |

**Sub-section: Scanned PDF Detection**
`_render_scanned_detection(text_result, sample_result, console)`

Table showing:
| Category | Count | % (CI) |
|----------|-------|--------|
| Native (has text layer) | N | XX.X% (CI: ...) |
| Scanned (image-only) | N | XX.X% (CI: ...) |
| Mixed (partial text) | N | XX.X% (CI: ...) |

- Compute confidence intervals using `compute_confidence_interval()` with PDF population from `sample_result.per_type_population`
- Format using `format_ci()`
- Only show this section if there are PDFs in the sample

**Sub-section: Content Classification**
`_render_content_classification(text_result, sample_result, console)`

Table showing:
| Classification | Count | % (CI) |
|----------------|-------|--------|
| Text-heavy (>500 chars/page) | N | XX.X% (CI: ...) |
| Image-heavy (<100 chars/page) | N | XX.X% (CI: ...) |
| Mixed (100-500 chars/page) | N | XX.X% (CI: ...) |

- Confidence intervals on the extractable file population

**Sub-section: Metadata Completeness**
`_render_metadata_completeness(text_result, sample_result, console)`

Table showing per-field completeness:
| Field | Files with value | % (CI) |
|-------|------------------|--------|
| Title | N | XX.X% (CI: ...) |
| Author | N | XX.X% (CI: ...) |
| Creation Date | N | XX.X% (CI: ...) |

- Per-field confidence intervals

**Section ordering in render_terminal_report():**
1. Header (existing)
2. File Type Distribution (existing)
3. Duplicate Detection (existing)
4. File Health (existing)
5. **Document Content Analysis (NEW)**
6. Size Distribution (existing)
7. File Age Distribution (existing)
8. Directory Structure (existing)
9. Issues (existing)
10. Footer (existing)

Update the Issues section `_render_issues()` to also accept text_result for extraction error reporting.

### Step 4: Create Test Fixtures

In `tests/conftest.py`, add fixture helpers:

```python
def create_minimal_pdf(path: Path, text: str = "Hello world", pages: int = 1) -> Path:
    """Create a minimal PDF with text content using pdfplumber-compatible format."""
    # Use reportlab-free approach: write raw PDF structure
    # Simple PDF with text objects on each page
    ...

def create_scanned_pdf(path: Path, pages: int = 1) -> Path:
    """Create a PDF with no text layer (simulates scanned document)."""
    # PDF with image XObjects but no text operators
    ...

def create_minimal_docx(path: Path, text: str = "Hello world",
                        title: str = "", author: str = "") -> Path:
    """Create a minimal DOCX with text and optional metadata."""
    from docx import Document
    doc = Document()
    doc.add_paragraph(text)
    if title:
        doc.core_properties.title = title
    if author:
        doc.core_properties.author = author
    doc.save(str(path))
    return path
```

Add fixtures:
```python
@pytest.fixture
def tmp_corpus_with_documents(tmp_path):
    """Corpus with PDFs and DOCXes for text extraction testing."""
    # 3 native PDFs with text
    # 1 scanned PDF (no text layer)
    # 2 DOCXes with metadata
    # 2 plain text files (not extractable by text.py)
    ...
```

**PDF creation without reportlab:**
Create raw PDF bytes manually using the PDF specification. A minimal PDF with text needs:
- Header: `%PDF-1.4`
- Catalog, Pages, Page objects
- Content stream with `BT /F1 12 Tf (text) Tj ET`
- Font resource
- Cross-reference table and trailer

For scanned PDFs: same structure but content stream has image reference (`/Im1 Do`) instead of text operators. No char objects will be found by pdfplumber.

### Step 5: Create Sampling Tests

Create `tests/test_sampling.py`:

**Test cases:**
1. `test_select_sample_basic` - Basic sampling at 10% rate
2. `test_select_sample_min_per_type` - Min 30 per type enforced (small corpus takes all)
3. `test_select_sample_census` - Rate 1.0 selects all files, is_census=True
4. `test_select_sample_stratified` - Multiple types get proportional samples
5. `test_select_sample_empty_walk` - Empty WalkResult returns empty sample
6. `test_confidence_interval_basic` - CI for 50% proportion, n=100, N=1000
7. `test_confidence_interval_census` - Census returns exact values, zero margin
8. `test_confidence_interval_small_sample` - Small n produces wider intervals
9. `test_confidence_interval_zero_successes` - 0 successes returns valid CI
10. `test_confidence_interval_all_successes` - All successes returns valid CI
11. `test_format_ci_sampled` - Format string includes CI range
12. `test_format_ci_census` - Format string shows "exact"

### Step 6: Create Text Extraction Tests

Create `tests/test_text.py`:

**Test cases:**
1. `test_extract_pdf_native` - Native PDF extracts text, chars_per_page > 0
2. `test_extract_pdf_scanned` - Scanned PDF detected, is_scanned=True
3. `test_extract_pdf_metadata` - PDF metadata fields extracted correctly
4. `test_extract_docx_text` - DOCX text extraction works
5. `test_extract_docx_metadata` - DOCX metadata (title, author) extracted
6. `test_extract_text_classification_text_heavy` - High chars/page = text_heavy
7. `test_extract_text_classification_image_heavy` - Low chars/page = image_heavy
8. `test_extract_text_aggregate_counts` - Aggregate result counts match
9. `test_extract_text_metadata_completeness` - Per-field completeness tallied
10. `test_extract_text_error_handling` - Corrupt file produces error, doesn't crash
11. `test_extract_text_empty_sample` - No extractable files returns empty result
12. `test_extract_text_progress_callback` - Progress callback called correctly

**Testing ProcessPoolExecutor:**
- Tests use actual ProcessPoolExecutor (not mocked) to verify crash isolation
- Use `max_workers=1` in tests for deterministic behavior
- Test timeout handling with a mock that's slow (or skip if flaky)

### Step 7: Run Full Test Suite

```bash
uv run pytest --cov --cov-fail-under=80 -v
```

Verify:
- All existing tests pass (69 from Phase 1+2)
- New sampling tests pass (~12 tests)
- New text extraction tests pass (~12 tests)
- Total coverage >= 80%

## Verification
- [ ] `uv run field-check scan ./tests/fixtures/ --sampling-rate 1.0` shows text analysis sections
- [ ] Scanned PDF detection section shows confidence intervals
- [ ] Metadata completeness section shows per-field percentages
- [ ] `--sampling-rate 0.5` produces different sample sizes
- [ ] `uv run pytest --cov --cov-fail-under=80` all tests pass
- [ ] `uv run ruff check .` no lint errors
- [ ] Report shows "(exact, N=X)" when sampling rate is 1.0 (census)
- [ ] Report shows "(CI: X% -- Y%, n=N)" when sampling rate < 1.0

## Done When
- `field-check scan <path>` runs sampling + text extraction as part of pipeline
- `--sampling-rate` CLI flag overrides config file value
- Terminal report shows Document Content Analysis section with:
  - Scanned PDF detection (native/scanned/mixed counts with CIs)
  - Content classification (text-heavy/image-heavy/mixed with CIs)
  - Metadata completeness (per-field percentages with CIs)
- Confidence intervals shown on all sampled metrics (Invariant #4)
- ProcessPoolExecutor isolates crashes (Invariant #5)
- ~24 new tests pass, total coverage >= 80%
- All 69 existing tests still pass

## Notes
- Creating raw PDFs without reportlab is tricky. Use minimal PDF structure that pdfplumber can parse. Test with both pdfplumber's page.chars and page.extract_text().
- DOCX fixtures use python-docx directly (it's a project dependency).
- ProcessPoolExecutor tests should use `max_workers=1` for deterministic ordering.
- The report sections only appear when there are extractable files (PDF/DOCX) in the sample. If the corpus is all images/text files, the text analysis section is skipped gracefully.
- Confidence interval display follows Invariant #4: "Sampled Results Show Confidence."
- Keep report section compact. Don't repeat information across sub-sections.
