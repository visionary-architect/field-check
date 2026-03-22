# Phase 1 User Acceptance Testing

## Date: 2026-03-03

## Tests Performed

### Test 1: field-check --version
**Status:** Pass
**Notes:** Prints `field-check, version 0.1.0`

### Test 2: field-check scan <path> produces report
**Status:** Pass
**Notes:** Full Rich terminal report with all 5 sections on mixed corpus (9 files, 8 types)

### Test 3: File types detected by magic bytes
**Status:** Pass
**Notes:** PNG → image/png, PDF → application/pdf via magic bytes. Extension fallback: .txt → text/plain, .csv → text/csv, .py → text/x-python, .json → text/json, .yaml → text/yaml

### Test 4: .field-check.yaml excludes work
**Status:** Pass
**Notes:** `exclude: ["*.bin"]` in config correctly excluded bigfile.bin (9 → 8 files)

### Test 5: --exclude CLI flag works
**Status:** Pass
**Notes:** `--exclude "*.py" --exclude "*.json"` reduced files (8 → 6). Multiple excludes stack.

### Test 6: Size/age/directory stats accurate
**Status:** Pass
**Notes:** Size buckets correct, age distribution correct (all <1 day for fresh files), directory structure (5 dirs, 3 empty) matches manual count

### Test 7: Permission errors handled gracefully
**Status:** Pass
**Notes:** Scanning C:\Windows\System32\config (restricted) completes without crash, produces clean empty report

### Test 8: pip install -e . works
**Status:** Pass
**Notes:** `uv pip install -e .` installs field-check 0.1.0 successfully

### Test 9: Automated test suite
**Status:** Pass
**Notes:** 47 passed, 2 skipped (symlinks on Windows), 84% coverage

## Summary
- **Passed:** 9 of 9 tests
- **Failed:** 0 of 9 tests

## Issues Found
None

## Verdict
- [x] Phase complete - all tests pass

## Deliverable Checklist
- [x] pyproject.toml with Click entry point, all core deps
- [x] `field-check scan <path>` command working
- [x] File walker with .field-check.yaml exclude support
- [x] File inventory: count, types (magic-byte via filetype), sizes
- [x] Directory structure analysis (depth/breadth)
- [x] File age distribution (mtime/ctime)
- [x] Basic Rich terminal report
- [x] Symlink loop detection, permission error handling
- [x] Tests with fixture corpus (84% coverage)

## Requirements Addressed
- [x] M1: Package skeleton
- [x] M2: Local folder scanning with excludes
- [x] M3: File inventory (count, types, sizes, structure)
- [x] M4: Basic terminal report via Rich
- [x] S1: .field-check.yaml config support
- [x] S2: Symlink loop detection
- [x] S3: Windows 260-char path handling (implemented, not testable without long paths)
- [x] S4: File age distribution
