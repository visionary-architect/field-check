# Phase 4 - Plan B Summary: CLI + Report Integration + Tests

## Status: Complete

## What Was Done
- Added `--show-pii-samples` CLI flag with privacy warning banner
- Wired PII scan step into CLI pipeline with progress spinner after text extraction
- Updated report dispatcher to pass `pii_result` through
- Added PII Risk Indicators section to terminal report with per-type breakdown and CIs
- Added page count distribution sub-section inside Document Content Analysis
- Added PII scan errors to Issues section
- Created `create_pdf_with_pii()` helper and `tmp_corpus_with_pii` fixture
- Created comprehensive test suite with 17 tests covering Luhn, patterns, integration, custom patterns, page counts

## Files Changed
- `src/field_check/cli.py` - Added --show-pii-samples flag, PII scan step, pii_result to report
- `src/field_check/report/__init__.py` - Added pii_result parameter passthrough
- `src/field_check/report/terminal.py` - Added _render_pii_results, _render_pii_samples, _render_page_count_distribution, updated _render_issues
- `tests/conftest.py` - Added create_pdf_with_pii() and tmp_corpus_with_pii fixture
- `tests/test_pii.py` - NEW: 17 tests for PII scanning

## Verification Results
- [x] Ruff lint passes on src/ and tests/
- [x] 107 tests pass (17 new PII tests + 90 existing), 3 skipped (Windows)
- [x] Coverage at 82.36% (above 80% threshold)

## Commit
- Hash: 159bf13
- Message: feat(4-B): integrate PII scanning and page count into CLI and report

## Notes
- PII section uses "PII Risk Indicators" title (not "Detection") per spec
- Per-type breakdown shows expected FP rate to calibrate user expectations
- Page count distribution rendered inside Document Content Analysis section
- PII match content NEVER stored unless --show-pii-samples (Invariant 3 verified via tests)
- All PII metrics show confidence intervals (Invariant 4)
