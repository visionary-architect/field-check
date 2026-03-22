# Phase 7 - Plan C: CLI Integration + Tests

## Overview
Wire CI exit codes into CLI, add auto-output-path logic, and create comprehensive tests for all three export formats + exit code logic.

## Prerequisites
- Plan A complete (JSON, CSV, exit code modules exist)
- Plan B complete (HTML module exists)

## Files to Create/Modify
- `src/field_check/cli.py` — MODIFIED: Add exit code logic + auto output path
- `tests/test_exports.py` — NEW: Tests for JSON, CSV, HTML, and exit codes
- `tests/conftest.py` — MODIFIED: Add export-related fixtures if needed

## Task Details

### Step 1: Update CLI for Exit Codes + Auto Output Path

In `src/field_check/cli.py`:

1. Add import: `from field_check.report import determine_exit_code`

2. Pass `config` to `generate_report()`:
   ```python
   generate_report(
       output_format, inventory, result, elapsed, output_path, console,
       config=config,
       dedup_result=dedup_result,
       ...
   )
   ```

3. After `generate_report()` call, add exit code logic:
   ```python
   # Determine CI exit code
   exit_code = determine_exit_code(
       config,
       inventory,
       dedup_result=dedup_result,
       corruption_result=corruption_result,
       pii_result=pii_result,
   )
   if exit_code != 0:
       sys.exit(exit_code)
   ```

4. The existing `sys.exit(2)` for errors is already in place (scan failure paths).

### Step 2: Create Test File

Create `tests/test_exports.py` with these test classes:

**TestJSONReport (7 tests):**

- `test_json_valid` — render_json_report returns valid JSON (json.loads doesn't raise)
- `test_json_has_summary` — output has "version", "scan_path", "scan_date", "summary" keys
- `test_json_has_files_array` — output has "files" array with correct count
- `test_json_file_entry_fields` — each file entry has path, size, mime_type, is_duplicate, health_status
- `test_json_no_pii_content` — JSON never contains matched PII text (Invariant 3) — only counts/types
- `test_json_dedup_data` — summary.duplicates section has correct counts when duplicates exist
- `test_json_null_optional_sections` — optional sections (pii, language, etc.) are null when not provided

**TestCSVReport (5 tests):**

- `test_csv_valid` — render_csv_report returns valid CSV (csv.reader can parse it)
- `test_csv_header_row` — first row has expected column names
- `test_csv_row_count` — row count equals number of files + 1 (header)
- `test_csv_no_pii_content` — CSV never contains matched PII text (Invariant 3)
- `test_csv_duplicate_flag` — is_duplicate column correctly flags duplicates

**TestHTMLReport (5 tests):**

- `test_html_valid` — render_html_report returns string containing `<!DOCTYPE html>`
- `test_html_has_sections` — output contains all section headings
- `test_html_self_contained` — no external URLs in href/src (except within commented Chart.js)
- `test_html_no_pii_content` — HTML never contains matched PII text (Invariant 3)
- `test_html_chart_js_present` — output contains Chart.js initialization code

**TestExitCodes (6 tests):**

- `test_exit_code_clean` — returns 0 when all metrics below thresholds
- `test_exit_code_pii_critical` — returns 1 when PII rate >= 5%
- `test_exit_code_duplicate_critical` — returns 1 when duplicate rate >= 10%
- `test_exit_code_corrupt_critical` — returns 1 when corrupt rate >= 1%
- `test_exit_code_custom_thresholds` — custom thresholds from config override defaults
- `test_exit_code_no_results` — returns 0 when optional results are None

**TestCLIExportIntegration (3 tests):**

Use Click's `CliRunner` to test:

- `test_cli_json_output` — `field-check scan <corpus> --format json` creates JSON file
- `test_cli_csv_output` — `field-check scan <corpus> --format csv` creates CSV file
- `test_cli_custom_output_path` — `--format json -o custom.json` creates file at specified path

**TestConfigThresholds (3 tests):**

- `test_default_thresholds` — config defaults to PII 0.05, dup 0.10, corrupt 0.01
- `test_yaml_thresholds` — parses thresholds section from YAML
- `test_yaml_threshold_clamping` — values outside 0-1 get clamped

### Step 3: Create Test Helpers

In tests, create minimal mock result objects for testing export modules without running actual scans:

```python
def _make_minimal_results():
    """Create minimal result objects for export testing."""
    # Create a small WalkResult with 3 files
    # Create matching InventoryResult
    # Create DedupResult with 1 duplicate group
    # Create CorruptionResult (all ok)
    # Create SampleResult
    # Return as dict of kwargs
```

This avoids needing to run full scans in export tests.

### Step 4: Full Test Run

- Run `uv run ruff check .` — lint clean
- Run `uv run pytest --cov --cov-fail-under=80` — all pass, coverage ≥80%

## Verification
- [ ] `uv run field-check scan <test-corpus> --format json` creates valid JSON file
- [ ] `uv run field-check scan <test-corpus> --format csv` creates valid CSV file
- [ ] `uv run field-check scan <test-corpus> --format html` creates valid HTML file
- [ ] Exit code is 0 for clean corpus, 1 for corpus exceeding thresholds
- [ ] All three export formats produce correct output
- [ ] `uv run ruff check .` — lint clean
- [ ] `uv run pytest --cov --cov-fail-under=80` — all pass, coverage ≥80%

## Done When
- CLI exit codes work (0 clean, 1 critical, 2 failed)
- Auto output paths work for all formats
- 29+ tests pass covering JSON, CSV, HTML, exit codes, CLI integration, and config
- All invariants respected (no PII content in exports)
- Coverage ≥80%

## Notes
- Click CliRunner handles sys.exit() — can assert `result.exit_code`
- For CLI integration tests, use `tmp_sample_corpus` fixture (already exists in conftest.py)
- JSON/CSV tests use mock results to avoid slow scan operations
- HTML tests check for string presence, not DOM parsing (no extra deps)
- Exit code logic is simple: check three rates against three thresholds, return 0 or 1
- For CLI integration tests, change CWD to tmp_path so auto-generated files don't pollute project
