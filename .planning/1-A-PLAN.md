# Phase 1 - Plan A: CLI Entry Point + Config Loader + File Walker

## Overview
Create the Click CLI with `scan` command, the `.field-check.yaml` config loader, and the core file walker that traverses directories with symlink detection, permission error handling, Windows long-path support, and exclude pattern filtering.

## Prerequisites
- pyproject.toml exists with Click entry point ✅
- `src/field_check/__init__.py` exists ✅

## Files to Create/Modify
- `src/field_check/cli.py` — Click CLI with `scan` command and progress bar
- `src/field_check/config.py` — `.field-check.yaml` loader with exclude patterns
- `src/field_check/scanner/__init__.py` — File walker: directory traversal, symlink loop detection, permission handling, Windows paths

## Task Details

### Step 1: Create `config.py` — Config Loader

Create `src/field_check/config.py`:

- Function `load_config(scan_path: Path) -> FieldCheckConfig` that:
  - Looks for `.field-check.yaml` in `scan_path` directory
  - Falls back to empty/default config if not found
  - Parses YAML using PyYAML (already available via other deps) or a simple parser
  - **Note:** PyYAML is NOT in deps. Use a lightweight approach: since Phase 1 only needs `exclude` patterns, parse the YAML file using a minimal approach. Add `pyyaml>=6.0` to dev deps only, or just handle the simple exclude list format manually. **Decision: add `pyyaml>=6.0` to core deps** — it's tiny and we'll need full YAML support for sampling config, PII custom patterns, and thresholds in later phases.
- `FieldCheckConfig` dataclass with fields:
  - `exclude: list[str]` — glob patterns to exclude (default: `[".git/", "__pycache__/", "node_modules/"]`)
  - (Keep it extensible — Phase 3 will add `sampling_rate`, `min_per_type`, etc. Don't add unused fields now.)
- Function `should_exclude(path: Path, patterns: list[str]) -> bool`:
  - Check path against exclude glob patterns
  - Use `fnmatch` or `pathlib.PurePath.match()` for pattern matching
  - Match against both the full relative path and just the filename

### Step 2: Create `scanner/__init__.py` — File Walker

Update `src/field_check/scanner/__init__.py`:

- Dataclass `FileEntry`:
  - `path: Path` — absolute path to file
  - `relative_path: Path` — relative to scan root
  - `size: int` — file size in bytes
  - `mtime: float` — modification time (epoch)
  - `ctime: float` — creation time (epoch)
  - `is_symlink: bool`
- Dataclass `WalkResult`:
  - `files: list[FileEntry]` — all discovered files
  - `total_size: int` — sum of all file sizes
  - `total_dirs: int` — total directories encountered
  - `empty_dirs: int` — directories containing zero files
  - `permission_errors: list[Path]` — paths we couldn't access
  - `symlink_loops: list[Path]` — detected symlink loops
  - `excluded_count: int` — number of files/dirs excluded by patterns
  - `scan_root: Path` — the root path that was scanned
- Function `walk_directory(root: Path, config: FieldCheckConfig, progress_callback: Callable | None = None) -> WalkResult`:
  - Use `os.walk()` with manual control (NOT `Path.rglob()` — need symlink control)
  - **Symlink loop detection:** Track visited `(dev, inode)` pairs (use `os.stat()` result). On Windows where inode may be 0, fall back to resolved path tracking.
  - **Permission errors:** Wrap `os.scandir()` / `os.walk()` in try/except, collect PermissionError paths, continue scanning
  - **Windows 260-char paths (S3):** Prefix paths with `\\?\` on Windows when path length > 259 chars. Use `os.fspath()` for safe conversion.
  - **Exclude filtering:** Check each directory/file against config exclude patterns before descending
  - **Skip special files:** Only include regular files (skip devices, pipes, sockets via `stat.S_ISREG`)
  - **Track directories:** Count total dirs and empty dirs during traversal (needed by Plan B's DirectoryStructure). A directory is "empty" if it contains zero regular files (subdirs don't count).
  - **Note on `ctime`:** On Unix, `ctime` = inode change time, NOT creation time. On Windows, `ctime` = creation time. Add a code comment documenting this. Age distribution in Plan B should primarily use `mtime`.
  - Call `progress_callback(file_count)` periodically for the progress bar

### Step 3: Create `cli.py` — Click CLI

Create `src/field_check/cli.py`:

- `@click.group()` main group with `--version` flag (reads `__version__`)
- `@main.command()` `scan` command:
  - Argument: `path` (required, type=click.Path(exists=True))
  - Option: `--config` (path to .field-check.yaml, overrides auto-detection)
  - Option: `--exclude` (multiple, additional exclude patterns)
  - Option: `--format` (choice: terminal/html/json/csv, default: terminal) — only terminal works in Phase 1
  - Option: `--output` / `-o` (output file path for non-terminal formats)
- Scan flow:
  1. Resolve and validate the path
  2. Load config (from --config or auto-detect in scan path)
  3. Merge --exclude CLI patterns into config
  4. Show Rich progress bar: `Scanning files...` with file count spinner
  5. Call `walk_directory()` with progress callback
  6. (Phase 1B will add inventory analysis here)
  7. (Phase 1C will add terminal report here)
  8. For now: print summary line — `Found {n} files ({size} total) in {path}`
- Use `rich.console.Console` for output
- Handle `KeyboardInterrupt` gracefully (show partial results message)
- Handle path-not-found / not-a-directory errors with clear messages

### Step 4: Add PyYAML dependency

Update `pyproject.toml`:
- Add `pyyaml>=6.0` to `dependencies`

### Step 5: Wire up and verify manually

- Run `uv sync` to install deps
- Run `uv run field-check --version` → should print version
- Run `uv run field-check scan .` → should walk current dir and print summary

## Verification
- [ ] `uv sync` succeeds
- [ ] `uv run field-check --version` prints `0.1.0`
- [ ] `uv run field-check scan .` walks directory and prints file count/size summary
- [ ] `uv run field-check scan --exclude "*.pyc" .` applies exclude filter
- [ ] Scanning a path with a symlink loop doesn't hang
- [ ] Permission errors are collected, not fatal
- [ ] `uv run ruff check src/` passes
- [ ] Type: `auto`

## Done When
`field-check scan <path>` walks a directory, respects excludes from `.field-check.yaml` and CLI flags, handles symlinks/permissions/Windows paths, and prints a file count summary.

## Notes
- The walker is the foundation everything else builds on — get the edge cases right here
- `os.walk()` with `followlinks=False` is the safe default; we track symlinks manually
- On Windows, `st_ino` can be 0 for some filesystems — use resolved path as fallback for loop detection
- Keep `FileEntry` lightweight — it's held in memory for every file in the corpus
