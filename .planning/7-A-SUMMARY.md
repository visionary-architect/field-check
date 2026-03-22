# Phase 7 - Plan A Summary: JSON + CSV Export Modules + CI Exit Codes + Config

## Status: Complete

## What Was Done
- Created JSON report renderer with summary stats + per-file data array
- Created CSV report renderer with file-level inventory and all flags
- Added CI exit code determination logic (0=clean, 1=critical, 2=failed)
- Added threshold config fields (pii_critical, duplicate_critical, corrupt_critical)
- Wired JSON and CSV formats into report dispatcher with auto output paths

## Files Changed
- `src/field_check/config.py` — MODIFIED: Added pii_critical (0.05), duplicate_critical (0.10), corrupt_critical (0.01) fields and YAML thresholds parsing
- `src/field_check/report/__init__.py` — MODIFIED: Added json/csv format handlers, determine_exit_code() function, auto output paths
- `src/field_check/report/json_report.py` — NEW: 230 lines. render_json_report() with summary + files array, per-file lookup builders
- `src/field_check/report/csv_report.py` — NEW: 130 lines. render_csv_report() with CSV_COLUMNS header and per-file rows

## Verification Results
- [x] All imports succeed
- [x] JSON export produces valid JSON with correct structure (version, scan_path, scan_date, summary, files)
- [x] CSV export produces valid CSV with header + data rows
- [x] Lint clean — all checks passed
- [x] End-to-end test: `field-check scan --format json` and `--format csv` both work

## Commit
- Hash: 53ab8d2
- Message: feat(7-A): add JSON and CSV export modules with CI exit codes

## Notes
- JSON never includes PII matched text (Invariant 3) — only counts and pattern types
- CSV never includes PII matched text either — only has_pii boolean and pii_types list
- Per-file blake3 hashes only available for files in duplicate groups (dedup module doesn't store single-file hashes)
- Auto output paths: field-check-report.json / field-check-report.csv in CWD
