# Phase 1 - Plan C: Test Suite + Fixtures

## Overview
Create the test infrastructure, fixture corpus, and comprehensive tests for all Phase 1 modules. Target 80%+ code coverage across cli.py, config.py, scanner/__init__.py, scanner/inventory.py, report/terminal.py.

## Prerequisites
- Plan A complete: cli.py, config.py, scanner/__init__.py
- Plan B complete: scanner/inventory.py, report/terminal.py, report/__init__.py
- `field-check scan <path>` produces a terminal report end-to-end

## Files to Create/Modify
- `tests/conftest.py` — Shared fixtures, temp directory corpus builder
- `tests/test_cli.py` — CLI integration tests (Click CliRunner)
- `tests/test_config.py` — Config loader tests
- `tests/test_inventory.py` — Inventory analyzer unit tests
- `tests/test_walker.py` — File walker tests (symlinks, permissions, excludes)

## Task Details

### Step 1: Create `tests/conftest.py` — Shared Fixtures

Create `tests/conftest.py`:

- `@pytest.fixture` `tmp_corpus(tmp_path)`:
  - Creates a temporary directory with a known set of test files:
    - `doc.txt` — small text file (100 bytes)
    - `report.pdf` — minimal valid PDF (use PDF header bytes + minimal structure)
    - `data.csv` — small CSV file
    - `image.png` — minimal valid PNG (8-byte header + IHDR chunk)
    - `empty.txt` — 0-byte file
    - `nested/deep/file.txt` — nested directory structure
    - `large.bin` — larger file (~10KB) for size distribution testing
  - Returns the tmp_path

- `@pytest.fixture` `tmp_corpus_with_symlinks(tmp_corpus)`:
  - Adds symlinks to tmp_corpus:
    - `link_to_doc.txt` → `doc.txt` (valid symlink)
    - `loop/` → `.` (symlink loop, if platform supports)
  - Skip on Windows if symlinks require admin

- `@pytest.fixture` `tmp_corpus_with_config(tmp_corpus)`:
  - Adds `.field-check.yaml` to tmp_corpus with:
    ```yaml
    exclude:
      - "*.bin"
      - "nested/"
    ```
  - Returns tmp_path

- `@pytest.fixture` `default_config()`:
  - Returns a `FieldCheckConfig` with default values

- Helper function `create_minimal_pdf(path: Path)`:
  - Write minimal valid PDF bytes (just enough for `filetype` to detect it)
  - `%PDF-1.4` header + minimal xref + trailer

- Helper function `create_minimal_png(path: Path)`:
  - Write PNG 8-byte signature + minimal IHDR chunk

### Step 2: Create `tests/test_config.py`

Tests for `src/field_check/config.py`:

- `test_load_default_config` — no .field-check.yaml → returns defaults
- `test_load_config_from_file` — parses .field-check.yaml correctly
- `test_load_config_invalid_yaml` — malformed YAML → falls back to defaults with warning
- `test_load_config_missing_fields` — partial YAML → fills in defaults
- `test_should_exclude_glob_pattern` — `*.pyc` matches `foo.pyc`
- `test_should_exclude_directory_pattern` — `node_modules/` matches `node_modules/foo.js`
- `test_should_exclude_no_match` — non-matching pattern returns False
- `test_default_excludes` — `.git/` and `__pycache__/` excluded by default

### Step 3: Create `tests/test_walker.py`

Tests for `walk_directory()` in `src/field_check/scanner/__init__.py`:

- `test_walk_basic` — walks tmp_corpus, finds expected file count
- `test_walk_file_entries` — FileEntry fields populated correctly (path, size, mtime, ctime)
- `test_walk_excludes_patterns` — config excludes filter out matching files/dirs
- `test_walk_cli_excludes` — additional CLI excludes work
- `test_walk_symlink_detection` — symlinks are detected (is_symlink=True)
- `test_walk_symlink_loop` — symlink loop detected and reported, doesn't hang
- `test_walk_permission_error` — inaccessible dir collected in permission_errors, scan continues
- `test_walk_empty_directory` — empty dir → 0 files, no crash
- `test_walk_nonexistent_path` — raises appropriate error
- `test_walk_single_file` — scanning a single file (not a directory) — handle gracefully
- `test_walk_progress_callback` — callback is invoked with incrementing counts
- `test_walk_excluded_count` — excluded_count reflects filtered items
- `test_walk_tracks_directories` — total_dirs and empty_dirs counted correctly
- `test_walk_empty_dir_counting` — dir with only subdirs (no files) counts as empty

### Step 4: Create `tests/test_inventory.py`

Tests for `src/field_check/scanner/inventory.py`:

- `test_analyze_inventory_basic` — processes tmp_corpus, returns InventoryResult
- `test_type_detection_pdf` — PDF detected as `application/pdf`
- `test_type_detection_png` — PNG detected as `image/png`
- `test_type_detection_text_fallback` — .txt files get `text/plain` via EXTENSION_MIME_MAP fallback
- `test_type_detection_csv_fallback` — .csv files get `text/csv` via extension fallback
- `test_type_detection_unknown` — unknown extension gets `application/octet-stream`
- `test_size_distribution_buckets` — files sorted into correct size buckets
- `test_size_distribution_stats` — min/max/median/mean calculated correctly
- `test_age_distribution` — files sorted into correct age buckets
- `test_directory_structure` — depth, breadth, empty dirs computed correctly
- `test_inventory_empty_corpus` — 0 files → zero stats, no crash
- `test_inventory_single_file` — 1 file → correct stats
- `test_type_detection_error_handling` — unreadable file → skipped, counted as error

### Step 5: Create `tests/test_cli.py`

Integration tests using Click's `CliRunner`:

- `test_cli_version` — `field-check --version` prints version
- `test_cli_scan_basic` — `field-check scan <path>` exits 0
- `test_cli_scan_output_contains_sections` — output contains "File Type", "Size Distribution", etc.
- `test_cli_scan_nonexistent_path` — exits with error, helpful message
- `test_cli_scan_with_exclude` — `--exclude "*.bin"` reduces file count
- `test_cli_scan_with_config` — `--config <path>` loads custom config
- `test_cli_scan_unsupported_format` — `--format html` shows "not yet supported"
- `test_cli_scan_file_count_in_output` — report shows correct total file count
- `test_cli_scan_shows_duration` — report output contains scan duration

### Step 6: Run tests and fix issues

- Run `uv run pytest --cov --cov-fail-under=80 -v`
- Fix any failures
- Verify coverage meets 80% threshold
- Run `uv run ruff check .` to confirm lint passes

## Verification
- [ ] `uv run pytest -v` — all tests pass
- [ ] `uv run pytest --cov --cov-fail-under=80` — coverage ≥ 80%
- [ ] `uv run ruff check .` — no lint errors
- [ ] Tests cover: config loading, file walking, inventory analysis, CLI commands
- [ ] Edge cases tested: empty dirs, symlink loops, permission errors, 0-byte files
- [ ] Type: `auto`

## Done When
All tests pass with 80%+ coverage. Test suite covers config, walker, inventory, and CLI integration. Edge cases (symlinks, permissions, empty files) are verified.

## Notes
- Use `pytest.mark.skipif` for platform-specific tests (symlinks on Windows)
- `CliRunner` captures output — assert on report sections, not exact formatting
- Minimal PDF/PNG fixtures: just enough bytes for `filetype` to detect the magic bytes
- Don't test exact Rich formatting — test that key data appears in output
- Permission error tests may need platform-specific handling (Windows vs Unix)
