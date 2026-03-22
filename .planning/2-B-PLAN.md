# Phase 2 - Plan B: Report Integration + Test Suite

## Overview
Wire up dedup and corruption scanners into the CLI pipeline, add terminal report sections for both, and create comprehensive tests for both new scanner modules.

## Prerequisites
- Phase 2 Plan A complete: `scanner/dedup.py` and `scanner/corruption.py` exist and return their respective result dataclasses

## Files to Create/Modify
- `src/field_check/cli.py` — Call `compute_hashes()` and `check_corruption()` in scan pipeline
- `src/field_check/report/__init__.py` — Pass DedupResult + CorruptionResult to terminal report
- `src/field_check/report/terminal.py` — Add dedup + corruption sections
- `tests/conftest.py` — Add fixtures for dedup/corruption testing (duplicate files, corrupt files, encrypted files)
- `tests/test_dedup.py` — Tests for dedup scanner
- `tests/test_corruption.py` — Tests for corruption scanner

## Task Details

### Step 1: Update CLI Pipeline (`cli.py`)

Add the new scanner calls to the `scan()` command, after inventory analysis:

```python
from field_check.scanner.dedup import compute_hashes
from field_check.scanner.corruption import check_corruption
```

After `analyze_inventory()`:
1. Add a new `console.status` block for hashing:
   ```python
   with console.status("[bold blue]Hashing files...", spinner="dots") as status:
       def on_hash(current: int, total: int) -> None:
           status.update(
               f"[bold blue]Hashing files... "
               f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
           )
       dedup_result = compute_hashes(result, progress_callback=on_hash)
   ```
2. Add a `console.status` block for corruption checking:
   ```python
   with console.status("[bold blue]Checking file health...", spinner="dots") as status:
       def on_check(current: int, total: int) -> None:
           status.update(
               f"[bold blue]Checking file health... "
               f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
           )
       corruption_result = check_corruption(result, progress_callback=on_check)
   ```
3. Pass both results through to `generate_report()`.

### Step 2: Update Report Dispatcher (`report/__init__.py`)

Update `generate_report()` signature to accept optional dedup and corruption results:

```python
from field_check.scanner.dedup import DedupResult
from field_check.scanner.corruption import CorruptionResult

def generate_report(
    fmt: str,
    inventory: InventoryResult,
    walk_result: WalkResult,
    elapsed_seconds: float,
    output_path: Path | None,
    console: Console,
    dedup_result: DedupResult | None = None,
    corruption_result: CorruptionResult | None = None,
) -> None:
```

Pass these through to `render_terminal_report()` as optional keyword arguments. Using `| None = None` keeps backward compat with Phase 1 and other report formats.

### Step 3: Add Terminal Report Sections (`report/terminal.py`)

Update `render_terminal_report()` to accept optional `dedup_result` and `corruption_result` parameters.

**Dedup section** (`_render_dedup_summary`), placed after File Type Distribution:
- Summary table with: Files hashed, Unique files, Duplicate groups, Duplicate files, Wasted space, Duplicate percentage
- If duplicate_groups exist, show a detail table (top 10 groups by wasted bytes):
  - Columns: Hash (first 12 hex chars), File Size, Copies, Wasted, Paths (first 3 + "and N more")
- If hash_errors > 0, add row to Issues section

**Corruption section** (`_render_corruption_summary`), placed after Dedup:
- Summary table with: Files checked, OK, Empty, Near-empty, Corrupt, Encrypted, Unreadable
- If flagged_files exist, show detail table (top 20):
  - Columns: Path (relative), Status, MIME Type, Detail
  - Color code: empty=dim, corrupt=red, encrypted=yellow, near_empty=dim, unreadable=yellow

### Step 4: Add Test Fixtures (`tests/conftest.py`)

Add these fixtures:

- `create_minimal_zip(path: Path) -> None` — helper that writes valid ZIP bytes (use `zipfile` module to create a small archive)
- `create_encrypted_zip(path: Path) -> None` — helper that writes a ZIP with encryption flag set in local header (manual byte manipulation to set bit 0 of general purpose flag at offset 6)
- `create_corrupt_pdf(path: Path) -> None` — writes a file with .pdf extension but PNG header bytes
- `create_encrypted_pdf(path: Path) -> None` — writes a minimal PDF with `/Encrypt` in the content

- `tmp_corpus_with_duplicates(tmp_path) -> Path` — fixture with:
  - 3 identical text files (same content)
  - 2 identical binary files (same random 1KB content)
  - 1 unique file
  - Returns the tmp_path

- `tmp_corpus_with_issues(tmp_path) -> Path` — fixture with:
  - 1 empty file (0 bytes)
  - 1 near-empty file (10 bytes)
  - 1 corrupt PDF (PNG header in .pdf extension)
  - 1 encrypted PDF (valid %PDF with /Encrypt)
  - 1 encrypted ZIP
  - 1 normal valid PDF
  - 1 normal valid PNG
  - Returns the tmp_path

### Step 5: Write `tests/test_dedup.py`

Tests for `scanner/dedup.py`:

1. **test_compute_hashes_all_unique** — Hash the standard `tmp_corpus`, verify all files have unique hashes, `duplicate_groups` is empty, `duplicate_bytes == 0`
2. **test_compute_hashes_finds_duplicates** — Use `tmp_corpus_with_duplicates`, verify 2 duplicate groups found, correct group sizes (3 and 2)
3. **test_compute_hashes_wasted_bytes** — Verify `duplicate_bytes` calculation: `file_size * (copies - 1)` for each group
4. **test_compute_hashes_duplicate_percentage** — Verify percentage calculation
5. **test_compute_hashes_empty_walk** — WalkResult with no files → `DedupResult(total_hashed=0, ...)`
6. **test_compute_hashes_progress_callback** — Verify callback is called with (current, total) for each file
7. **test_hash_deterministic** — Hash same file content twice, verify same BLAKE3 hash
8. **test_compute_hashes_permission_error** — Create a file, remove read permission (skip on Windows), verify `hash_errors` incremented

### Step 6: Write `tests/test_corruption.py`

Tests for `scanner/corruption.py`:

1. **test_check_empty_file** — 0-byte file → status "empty"
2. **test_check_near_empty_file** — 10-byte file → status "near_empty"
3. **test_check_valid_pdf** — Valid minimal PDF → status "ok"
4. **test_check_valid_png** — Valid minimal PNG → status "ok"
5. **test_check_corrupt_pdf** — PNG header in .pdf file → status "corrupt"
6. **test_check_encrypted_pdf** — PDF with /Encrypt → status "encrypted_pdf"
7. **test_check_encrypted_zip** — ZIP with encryption flag → status "encrypted_zip"
8. **test_check_normal_zip** — Valid non-encrypted ZIP → status "ok"
9. **test_corruption_result_counts** — Use `tmp_corpus_with_issues`, verify all counts match expected
10. **test_only_flagged_in_results** — Verify ok files NOT in `flagged_files` list
11. **test_check_corruption_empty_walk** — WalkResult with no files → `CorruptionResult(total_checked=0, ...)`
12. **test_check_corruption_progress_callback** — Verify callback called correctly
13. **test_unreadable_file** — File that raises OSError on read → status "unreadable"

### Step 7: Run Tests and Lint

- `uv run ruff check src/` — Must pass
- `uv run ruff format --check src/` — Must pass
- `uv run pytest --cov --cov-fail-under=80` — Must pass at 80%+

## Verification
- [ ] CLI `field-check scan <path>` runs full pipeline including hash + corruption check
- [ ] Terminal report shows Dedup section when duplicates exist
- [ ] Terminal report shows Corruption section when flagged files exist
- [ ] `uv run ruff check src/` passes
- [ ] `uv run pytest --cov --cov-fail-under=80` passes at 80%+
- [ ] Type: `auto`

## Done When
Both scanner modules are wired into the CLI, terminal report displays dedup and corruption summaries, and a comprehensive test suite covers all scanner functionality with 80%+ coverage.

## Notes
- Report parameters use `| None = None` for backward compatibility — Phase 1 tests still pass without dedup/corruption results
- Top 10 duplicate groups by wasted bytes keeps the report readable for large corpora
- Corrupt file detail table capped at 20 entries to keep report manageable
- Using `_format_size()` from existing terminal.py for consistent size formatting
- Encrypted PDF detection is simple byte search for `/Encrypt` — documented as not 100% reliable but good enough
- `create_encrypted_zip` needs manual byte patching — Python's zipfile module can't create encrypted ZIPs easily
