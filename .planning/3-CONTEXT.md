# Phase 3 Context

> Implementation decisions captured via /discuss-phase 3

## Phase Overview
Stratified sampling framework, text extraction pipeline (PDF + DOCX), scanned PDF detection, image-heavy classification, metadata completeness check, confidence intervals, and process pool crash isolation.

**Requirements:** M7, M8, M9, S5, S6, S10

## Decisions Made

### 1. Process Pool Isolation Strategy
**Question:** How to isolate file extraction to prevent crashes from malformed files
**Decision:** `concurrent.futures.ProcessPoolExecutor` with per-file timeout
**Rationale:** Standard library, automatic worker restart on crashes, handles C-level segfaults from pdfplumber/python-docx. Clean API with `submit()` + `future.result(timeout=)`.

### 2. Text Extraction — Single Pass
**Question:** Whether to extract text, metadata, page count, and scanned detection in one file open or multiple
**Decision:** Single pass per file — one function opens the file once and extracts everything
**Rationale:** pdfplumber is slow to open PDFs. Opening once and extracting text + page count + metadata + scanned flag + text density is significantly more efficient than multiple passes.

### 3. Scanned PDF Detection Method
**Question:** How to determine if a PDF is scanned (image-only) vs native (has text layer)
**Decision:** Check `page.chars` objects — if pages have zero char objects, they're scanned
**Rationale:** Most accurate method. pdfplumber exposes `page.chars` which is a list of character objects on the page. Zero chars = no text layer = scanned. Can classify individual pages as scanned or native, supporting "mixed" classification.

### 4. Image-Heavy Classification
**Question:** How to classify documents as image-heavy vs text-heavy
**Decision:** Both metrics combined — chars/page as primary, text-to-file-size ratio as secondary
**Rationale:** Chars/page is intuitive (< 100 = image-heavy, > 500 = text-heavy). File-size ratio catches cases where PDFs have large embedded images inflating file size. Combined approach gives most accurate classification.

**Thresholds:**
- Primary: chars/page — <100 = image-heavy, 100-500 = mixed, >500 = text-heavy
- Secondary: text_bytes/file_size — <5% = image-heavy signal

### 5. Metadata Completeness
**Question:** How to define and report metadata completeness
**Decision:** Per-field reporting — percentage of files with each field (title, author, creation date) separately
**Rationale:** Most actionable for users — shows exactly which metadata is most commonly missing. Data teams need to know "72% have title but only 45% have author" to prioritize fixes.

### 6. Sampling Config Integration
**Question:** Where to store sampling configuration (rate, min per type)
**Decision:** Add `sampling_rate` and `sampling_min_per_type` to existing `FieldCheckConfig`
**Rationale:** Single config object, configurable via `.field-check.yaml` and CLI `--sampling-rate` flag. Avoids passing multiple config objects.

## Locked Decisions
These decisions are now locked for planning:
- ProcessPoolExecutor for crash isolation
- Single-pass text extraction per file
- page.chars check for scanned PDF detection
- Combined chars/page + size ratio for image-heavy classification
- Per-field metadata completeness reporting
- Sampling config in FieldCheckConfig

## Open Questions
- Per-file timeout value for ProcessPoolExecutor (30s default? configurable?)
- Max worker count for ProcessPoolExecutor (cpu_count() or fixed?)
- DOCX metadata field names (python-docx CoreProperties API)
