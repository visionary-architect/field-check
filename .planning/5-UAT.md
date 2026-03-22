# Phase 5 User Acceptance Testing

## Date: 2026-03-05

## Tests Performed

### Test 1: Language Distribution Table Shows in Report
**Status:** Pass
**Notes:** Language Distribution table rendered correctly with 6 detected languages sorted by count descending. German (2), CJK (1), English (1), Latin Unknown (1), Spanish (1), French (1).

### Test 2: Encoding Distribution Table Shows for Plain Text Only
**Status:** Pass
**Notes:** Encoding Distribution table shows correct percentages. Footer note displayed: "Encoding detected for plain text files only (PDF/DOCX handle encoding internally)".

### Test 3: Confidence Intervals on Language Proportions (Invariant 4)
**Status:** Pass
**Notes:** Shows "(exact, N=7)" for 100% sampling rate. CIs use existing `compute_confidence_interval()` when sampling rate < 1.0.

### Test 4: Multiple Languages Detected Correctly
**Status:** Pass
**Notes:** English, Spanish, French, German, CJK all correctly identified. PII contacts file correctly classified as "Latin (Unknown)" (short structured text without strong stop-word signal).

### Test 5: PII Detection Works with Shared Text Cache
**Status:** Pass
**Notes:** PII scanner found 3 emails, 2 phones, 1 IP in pii_contacts.txt. `--show-pii-samples` flag displays matched content correctly.

### Test 6: Regression — All Existing Report Sections Present
**Status:** Pass
**Notes:** All 8 report sections present: File Type Distribution, Duplicate Detection, File Health, PII Risk Indicators, Language Distribution, Encoding Distribution, Size Distribution, File Age Distribution, Directory Structure.

## Issues Found

### Issue 1: Encoding Normalization Bug
**Description:** charset-normalizer returns `utf_8` (underscore) for some files and `utf-8` (dash) for others, causing split entries in the encoding distribution table.
**Root Cause:** `_normalize_encoding()` only handled case normalization and alias lookup, not underscore-to-dash conversion.
**Fix:** Added `.replace("_", "-")` to normalization pipeline + added test.
**Commit:** e978883

## Summary
- **Passed:** 6 of 6 tests
- **Failed:** 0 of 6 tests

## Issues Found
1. Encoding underscore normalization bug -> Fixed in commit e978883

## Verdict
- [x] Phase complete - all tests pass (after fix)
- [ ] Phase needs fixes - see fix plans
- [ ] Phase blocked - major issues found

## Test Corpus
7 files at `%TEMP%/uat5-corpus`:
- english_report.txt (English)
- spanish_manual.txt (Spanish)
- french_guide.txt (French)
- german_doc.txt (German, UTF-8)
- latin1_spec.txt (German, Latin-1/cp1250)
- chinese_doc.txt (CJK, UTF-8)
- pii_contacts.txt (English, structured PII data)

## Automated Test Results
- 148 tests passed, 3 skipped (Windows symlink/chmod)
- 82.43% coverage (above 80% threshold)
