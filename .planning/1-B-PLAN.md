# Phase 1 - Plan B: Inventory Analysis + Terminal Report

## Overview
Build the file inventory analyzer (magic-byte type detection, size distribution, directory structure, file age distribution) and the Rich terminal report that displays all findings.

## Prerequisites
- Plan A complete: cli.py, config.py, scanner/__init__.py with file walker
- `walk_directory()` returns `WalkResult` with `list[FileEntry]`

## Files to Create/Modify
- `src/field_check/scanner/inventory.py` — File type detection, size/age/structure analysis
- `src/field_check/report/terminal.py` — Rich terminal report
- `src/field_check/report/__init__.py` — Report dispatcher
- `src/field_check/cli.py` — Wire inventory + report into scan command

## Task Details

### Step 1: Create `scanner/inventory.py` — Inventory Analyzer

Create `src/field_check/scanner/inventory.py`:

- Dataclass `InventoryResult`:
  - `total_files: int`
  - `total_size: int` (bytes)
  - `type_counts: dict[str, int]` — file type → count (e.g., `{"application/pdf": 1234, "text/plain": 567}`)
  - `type_sizes: dict[str, int]` — file type → total bytes
  - `extension_counts: dict[str, int]` — extension → count (e.g., `{".pdf": 1234}`)
  - `size_distribution: SizeDistribution` — bucketed size ranges
  - `age_distribution: AgeDistribution` — bucketed age ranges
  - `dir_structure: DirectoryStructure` — depth/breadth metrics
  - `permission_errors: int` — count from walk
  - `symlink_loops: int` — count from walk
  - `excluded_count: int` — count from walk

- Dataclass `SizeDistribution`:
  - `buckets: list[SizeBucket]` — e.g., <1KB, 1-10KB, 10-100KB, 100KB-1MB, 1-10MB, 10-100MB, >100MB
  - `min_size: int`, `max_size: int`, `median_size: int`, `mean_size: float`

- Dataclass `SizeBucket`:
  - `label: str`, `min_bytes: int`, `max_bytes: int`, `count: int`, `total_bytes: int`

- Dataclass `AgeDistribution`:
  - `buckets: list[AgeBucket]` — e.g., <1 day, 1-7 days, 7-30 days, 1-6 months, 6-12 months, >1 year
  - `oldest: datetime`, `newest: datetime`

- Dataclass `AgeBucket`:
  - `label: str`, `count: int`

- Dataclass `DirectoryStructure`:
  - `total_dirs: int` — from WalkResult.total_dirs
  - `max_depth: int`
  - `avg_depth: float`
  - `max_breadth: int` — largest number of files in a single directory
  - `avg_breadth: float`
  - `empty_dirs: int` — from WalkResult.empty_dirs

- Constant `EXTENSION_MIME_MAP: dict[str, str]` — fallback mapping for files where `filetype.guess()` returns None:
  - `.txt` → `text/plain`, `.csv` → `text/csv`, `.json` → `application/json`
  - `.py` → `text/x-python`, `.md` → `text/markdown`, `.xml` → `text/xml`
  - `.html`/`.htm` → `text/html`, `.yaml`/`.yml` → `text/yaml`
  - `.log` → `text/plain`, `.tsv` → `text/tab-separated-values`
  - Final fallback for unmapped extensions: `application/octet-stream`

- Function `analyze_inventory(walk_result: WalkResult, progress_callback: Callable | None = None) -> InventoryResult`:
  - **File type detection:** Use `filetype.guess(path)` for each file. If it returns None, look up extension in `EXTENSION_MIME_MAP`. If extension not mapped, use `application/octet-stream`.
  - **Important:** filetype.guess() reads the file header — this is I/O. Use a Rich progress bar.
  - **Size distribution:** Bucket files into standard ranges, compute stats (min/max/median/mean)
  - **Age distribution:** Use `mtime` from FileEntry (not ctime — see Plan A note on platform differences), bucket into time ranges relative to scan time
  - **Directory structure:** Use `total_dirs`, `empty_dirs` from WalkResult. Compute depth/breadth from file paths — track unique parent directories, path depths, files-per-directory.
  - Handle `PermissionError` and `OSError` on individual file type detection — skip and count errors

### Step 2: Create `report/terminal.py` — Rich Terminal Report

Create `src/field_check/report/terminal.py`:

- Function `render_terminal_report(inventory: InventoryResult, walk_result: WalkResult, elapsed_seconds: float, console: Console) -> None`:
  - Use `rich.table.Table`, `rich.panel.Panel`, `rich.columns.Columns`
  - **Header panel:** "Field Check — Document Corpus Health Report"
    - Scan path, scan date, total files, total size (human-readable), scan duration
  - **Section 1: File Type Distribution**
    - Table: Type | Count | % | Total Size | Avg Size
    - Sorted by count descending
    - Top 15 types, then "Other (N types)" row if more
  - **Section 2: Size Distribution**
    - Table: Range | Count | % | bar chart (using rich)
    - Stats: min, max, median, mean
  - **Section 3: File Age Distribution**
    - Table: Age Range | Count | %
    - Oldest and newest file dates
  - **Section 4: Directory Structure**
    - Total directories, max depth, avg depth
    - Max breadth (largest single directory), avg breadth
    - Empty directories count
  - **Section 5: Issues**
    - Permission errors count (if any)
    - Symlink loops detected (if any)
    - Excluded files/dirs count
  - **Footer:** "Field Check v{version} — All processing local. No data transmitted."
  - Use `rich.text.Text` for colorized status: green = good, yellow = warning, red = critical
  - Keep output concise — aim for fitting in one terminal screen for small corpora

### Step 3: Create `report/__init__.py` — Report Dispatcher

Update `src/field_check/report/__init__.py`:

- Function `generate_report(format: str, inventory: InventoryResult, walk_result: WalkResult, elapsed_seconds: float, output_path: Path | None, console: Console) -> None`:
  - `"terminal"` → call `render_terminal_report()`
  - Other formats → raise `ValueError(f"Format '{format}' not yet supported. Available: terminal")` (let cli.py catch and convert to click error — keeps report module decoupled from Click)

### Step 4: Wire into `cli.py`

Update the `scan` command in `cli.py`:

1. Record `scan_start = time.monotonic()` before walk
2. After `walk_directory()`, show type detection progress bar: `Analyzing file types...`
3. Call `analyze_inventory(walk_result)`
4. Record `elapsed = time.monotonic() - scan_start`
5. Call `generate_report("terminal", inventory, walk_result, elapsed, output_path, console)`
6. Wrap `generate_report` in try/except `ValueError` → convert to `click.UsageError`
7. Remove the temporary summary print from Plan A

### Step 5: Manual verification

- Run `uv run field-check scan .` → should show full Rich terminal report
- Run on a directory with mixed file types to verify type detection
- Verify human-readable sizes (KB, MB, GB formatting)

## Verification
- [ ] `uv run field-check scan .` produces a formatted Rich terminal report
- [ ] File types are detected by magic bytes (not just extension)
- [ ] Size distribution shows correct bucketed ranges
- [ ] Age distribution shows relative time buckets
- [ ] Directory structure metrics are accurate
- [ ] Permission errors / symlink loops shown in Issues section (when present)
- [ ] Report fits in terminal, looks professional
- [ ] `uv run ruff check src/` passes
- [ ] Type: `auto`

## Done When
`field-check scan <path>` produces a complete, well-formatted Rich terminal report showing file type distribution, size distribution, age distribution, directory structure analysis, and any issues encountered.

## Notes
- `filetype.guess()` returns `None` for plain text files — need extension fallback
- Human-readable sizes: use `rich.filesize.decimal()` or manual formatting
- Keep the report compact — users scanning 50K files don't want 50K lines of output
- Color coding: green for info, yellow for warnings (many permission errors), red for critical issues
- The report structure established here will be reused by HTML/JSON/CSV in Phase 7
