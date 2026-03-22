# Phase 5 - Plan A Summary: Language + Encoding Scanner Modules + Shared Text Cache

## Status: Complete

## What Was Done
- Created language detection module with Unicode script ranges (10 scripts) and 7 Latin stop-word profiles
- Created encoding result aggregation module with canonical name normalization
- Added shared text cache builder (`build_text_cache()`) to text.py for PDF/DOCX/plain text extraction
- Refactored PII scanner to accept pre-extracted text cache, eliminating duplicate file reads

## Files Changed
- `src/field_check/scanner/language.py` — NEW: 294 lines. Unicode scripts (Latin, CJK, Japanese Kana, Arabic, Cyrillic, Devanagari, Greek, Hangul, Thai, Hebrew) + stop-word profiles (EN, ES, FR, DE, PT, IT, NL). Functions: `detect_language()`, `analyze_languages()`.
- `src/field_check/scanner/encoding.py` — NEW: 83 lines. `EncodingResult` dataclass, `analyze_encodings()` aggregation, encoding name normalization.
- `src/field_check/scanner/text.py` — MODIFIED: Added `TextCacheResult`, `_extract_text_for_cache()` worker, `build_text_cache()` with ProcessPoolExecutor. Added `PLAIN_TEXT_MIMES`, `CACHE_EXTRACTABLE_MIMES` constants.
- `src/field_check/scanner/pii.py` — MODIFIED: Added `_scan_text_for_pii()` for cached text, `_aggregate_file_result()` helper. Modified `scan_pii()` to accept `text_cache` parameter and split processing between cached (direct scan) and uncached (process pool) files.

## Verification Results
- [x] English detection: "English" ✓
- [x] French detection: "French" ✓
- [x] Spanish detection: "Spanish" ✓
- [x] German detection: "German" ✓
- [x] CJK detection: "CJK" ✓
- [x] Japanese detection: "Japanese" ✓
- [x] Korean detection: "Korean" ✓
- [x] Arabic detection: "Arabic" ✓
- [x] Cyrillic detection: "Cyrillic" ✓
- [x] Short text: "Unknown" ✓
- [x] Encoding normalization (ascii→utf-8, case-insensitive) ✓
- [x] Lint clean ✓
- [x] All 107 existing tests pass ✓

## Commit
- Hash: c3eaee4
- Message: feat(5-A): add language and encoding scanner modules with shared text cache

## Notes
- Lowered MIN_CHARS_FOR_DETECTION from 50 to 20 because CJK characters are information-dense (1 char ≈ 1 word)
- Japanese detection uses both CJK + Kana presence check; Korean uses Hangul script detection
- Encoding normalization maps ascii→utf-8 (subset), utf-8-sig→utf-8, various aliases to canonical forms
