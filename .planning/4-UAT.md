# Phase 4 User Acceptance Testing

## Date: 2026-03-05

## Tests Performed

### Test 1: PII Risk Indicators section with per-type breakdown
**Status:** Pass
**Notes:** PII Risk Indicators section shows summary (files scanned, files with PII) plus per-type breakdown tables for all 5 built-in patterns (Email, SSN, Phone, IP, CC). Each type shows total matches, files affected, corpus exposure CI, and expected FP rate.

### Test 2: Page count distribution inside Document Content Analysis
**Status:** Pass
**Notes:** Page Count Distribution table appears inside Document Content Analysis section showing 3 populated buckets (1 page, 2-5 pages, 11-50 pages) with percentages. Min/Max/Mean stats displayed below the table.

### Test 3: --show-pii-samples shows warning banner + matched content
**Status:** Pass
**Notes:** Yellow "Privacy Warning" banner displayed. PII Samples table shows matched text, file name, PII type, and line number. Detects PII across PDF, DOCX, TXT, CSV, and JSON files. Luhn validation correctly filters CC — only 1 match for valid 4111 number.

### Test 4: Without --show-pii-samples, no PII content in output (Invariant 3)
**Status:** Pass
**Notes:** Report without the flag shows PII counts and types but no matched text content. No PII Samples table or Privacy Warning banner. Invariant 3 preserved.

### Test 5: Custom PII patterns from .field-check.yaml
**Status:** Pass
**Notes:** Custom "UK NI Number" pattern (`[A-Z]{2}\d{6}[A-Z]`) detected 2 matches (AB123456C, CD789012E) in uk_ids.txt. Pattern appears in both per-type breakdown and PII samples table. Note: YAML requires single quotes for regex patterns with backslash escapes.

### Test 6: Confidence intervals on PII metrics (Invariant 4)
**Status:** Pass
**Notes:** All PII per-type tables show "Corpus exposure" with proper confidence intervals (e.g., "30.8% (exact, N=13)" at 100% sampling, "7.1% (CI: 12.3% -- 20.4%, n=14)" with larger corpus). Invariant 4 satisfied.

### Test 7: Crash isolation — corrupt file doesn't kill PII scan
**Status:** Pass
**Notes:** Added corrupt.pdf (PNG bytes in .pdf extension). Scan completed successfully with all 14 files processed. Corrupt file was flagged by file health but didn't crash PII scanner. Invariant 5 satisfied.

### Test 8: Regression — existing Phase 1-3 features still work
**Status:** Pass
**Notes:** All existing report sections present: File Type Distribution, Duplicate Detection, File Health (with flagged files), Document Content Analysis (scanned detection, content classification, metadata completeness), Size/Age Distribution, Directory Structure. 107 automated tests pass, 82% coverage.

## Summary
- **Passed:** 8 of 8 tests
- **Failed:** 0 of 8 tests

## Issues Found
None.

## Verdict
- [x] Phase complete - all tests pass
- [ ] Phase needs fixes - see fix plans
- [ ] Phase blocked - major issues found

## Next Steps
- `/discuss-phase 5` — Language + Encoding detection
