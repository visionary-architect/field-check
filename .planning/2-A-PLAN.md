# Phase 2 - Plan A: BLAKE3 Dedup + Corruption/Encryption Scanners

## Overview
Create two new scanner modules: `dedup.py` for BLAKE3 content hashing and exact duplicate detection, and `corruption.py` for corrupt/encrypted/empty file detection. These are standalone analysis engines — report integration happens in Plan B.

## Prerequisites
- Phase 1 complete: walker produces `WalkResult` with `list[FileEntry]`
- blake3 package already in dependencies

## Files to Create/Modify
- `src/field_check/scanner/dedup.py` — BLAKE3 hashing + duplicate grouping
- `src/field_check/scanner/corruption.py` — Corrupt, encrypted, and empty file detection

## Task Details

### Step 1: Create `scanner/dedup.py` — BLAKE3 Dedup Scanner

Create `src/field_check/scanner/dedup.py`:

- Dataclass `DuplicateGroup`:
  - `hash: str` — hex BLAKE3 hash
  - `size: int` — file size (all files in group share same size)
  - `paths: list[Path]` — list of file paths with identical content

- Dataclass `DedupResult`:
  - `total_hashed: int` — number of files successfully hashed
  - `hash_errors: int` — files that couldn't be hashed (permission/read errors)
  - `unique_files: int` — number of unique content hashes
  - `duplicate_groups: list[DuplicateGroup]` — groups of 2+ files with same hash
  - `duplicate_file_count: int` — total number of files that are duplicates (including all copies)
  - `duplicate_bytes: int` — total bytes wasted by duplicates (group_size * (copies - 1) for each group)
  - `duplicate_percentage: float` — duplicate_file_count / total_hashed * 100

- Function `compute_hashes(walk_result: WalkResult, progress_callback: Callable[[int, int], None] | None = None) -> DedupResult`:
  - Iterate over all files in walk_result.files
  - For each file, compute BLAKE3 hash:
    ```python
    import blake3
    hasher = blake3.blake3()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):  # 64KB chunks
            hasher.update(chunk)
    file_hash = hasher.hexdigest()
    ```
  - Collect hashes in `dict[str, list[Path]]`
  - Skip files that raise PermissionError/OSError — increment hash_errors
  - After hashing all files, filter for groups with 2+ paths → duplicate_groups
  - Compute duplicate_bytes: `sum(group.size * (len(group.paths) - 1) for group in duplicate_groups)`
  - Call `progress_callback(current, total)` per file

- **Performance note:** BLAKE3 is Rust-backed and very fast (~1GB/s). Sequential hashing is fine for Phase 2. No need for multiprocessing here — the I/O is the bottleneck, not the hash computation.

- **Memory note:** Only store hash→paths mapping. For 1M files with 64-char hex hashes, this is ~100MB — fine per SPEC (SQLite fallback at 10M+).

### Step 2: Create `scanner/corruption.py` — Corruption Detection

Create `src/field_check/scanner/corruption.py`:

- Constant `MAGIC_SIGNATURES: dict[str, list[bytes]]` — expected magic bytes per MIME type:
  - `application/pdf` → `[b"%PDF"]`
  - `application/zip` → `[b"PK\x03\x04", b"PK\x05\x06"]` (also covers DOCX/XLSX/PPTX)
  - `image/png` → `[b"\x89PNG"]`
  - `image/jpeg` → `[b"\xff\xd8\xff"]`
  - `image/gif` → `[b"GIF87a", b"GIF89a"]`
  - `application/gzip` → `[b"\x1f\x8b"]`

- Constant `NEAR_EMPTY_THRESHOLD: int = 50` — files under 50 bytes considered "near-empty"

- Enum or string constants for file status:
  - `"ok"` — file appears valid
  - `"empty"` — 0 bytes
  - `"near_empty"` — 1-50 bytes (too small for meaningful content)
  - `"corrupt"` — magic byte mismatch (extension says PDF, header says otherwise)
  - `"encrypted_pdf"` — PDF with /Encrypt dictionary
  - `"encrypted_zip"` — ZIP with encryption flag set
  - `"unreadable"` — couldn't open/read

- Dataclass `FileHealth`:
  - `path: Path`
  - `status: str` — one of the status constants above
  - `mime_type: str` — detected MIME type
  - `detail: str` — human-readable detail (e.g., "PDF header missing", "ZIP encrypted")

- Dataclass `CorruptionResult`:
  - `total_checked: int`
  - `ok_count: int`
  - `empty_count: int` — 0-byte files
  - `near_empty_count: int` — 1-50 byte files
  - `corrupt_count: int` — magic byte mismatches
  - `encrypted_count: int` — encrypted PDFs + ZIPs
  - `unreadable_count: int` — permission/read errors
  - `flagged_files: list[FileHealth]` — all non-ok files (for report detail)

- Function `check_corruption(walk_result: WalkResult, progress_callback: Callable[[int, int], None] | None = None) -> CorruptionResult`:
  - For each file:
    1. **Empty check:** `entry.size == 0` → status "empty"
    2. **Near-empty check:** `0 < entry.size <= NEAR_EMPTY_THRESHOLD` → status "near_empty"
    3. **Magic byte validation:** Read first 8 bytes, compare against MAGIC_SIGNATURES for the file's detected MIME type (from `filetype.guess()`). If extension/MIME suggests PDF but header doesn't start with `%PDF`, mark as "corrupt".
    4. **Encrypted PDF:** If file starts with `%PDF`, read first ~4KB and check for `/Encrypt` string. Use simple byte search, not full PDF parsing.
    5. **Encrypted ZIP:** If file starts with `PK\x03\x04`, read bytes 6-7 (general purpose bit flag). If bit 0 is set, the ZIP is encrypted.
    6. Skip files that can't be read → status "unreadable"
  - Only add non-ok files to `flagged_files` list (keep memory bounded)
  - Call `progress_callback(current, total)` per file

- **Important:** This reads file headers (first few KB). For 50K files, this is fast (~seconds). No multiprocessing needed.

- **Important:** Never read full file content for corruption detection — just headers.

### Step 3: Verify modules independently

- Write a quick smoke test in Python REPL or a small script:
  - Hash a known file, verify BLAKE3 hash is stable
  - Create a corrupt file (rename .txt to .pdf), verify it's detected
  - Test with an empty file

## Verification
- [ ] `scanner/dedup.py` can hash files and find duplicates
- [ ] `scanner/corruption.py` can detect empty, corrupt, encrypted files
- [ ] Both modules handle PermissionError/OSError gracefully
- [ ] `uv run ruff check src/` passes
- [ ] Type: `auto`

## Done When
Both scanner modules exist, can process a `WalkResult`, and return their respective result dataclasses. They handle errors gracefully and don't crash on unreadable files.

## Notes
- BLAKE3 hashes ALL files — sampling doesn't work for dedup (SPEC requirement)
- 64KB read chunks for hashing balance memory vs syscall overhead
- Encrypted PDF detection uses byte search for `/Encrypt`, not full PDF parse
- ZIP encryption uses bit flag in local file header, not central directory
- DOCX/XLSX/PPTX are ZIP files — encrypted OOXML detected by ZIP flag check
- Corruption check is header-only — never reads full file content
- `filetype.guess()` is already called in inventory.py — consider passing detected types to avoid double I/O. But since filetype only reads the first few bytes and OS caches them, the overhead is negligible. Keep modules independent for now.
