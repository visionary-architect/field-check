# Phase 6 - Plan B: CLI + Report Integration + Tests

## Overview
Wire SimHash near-duplicate detection into the CLI pipeline, add report section with summary stats and cluster list, and write comprehensive tests.

## Prerequisites
- Plan A complete (`simhash.py` module and config update exist)

## Files to Create/Modify
- `src/field_check/cli.py` — MODIFIED: Add SimHash pipeline step
- `src/field_check/report/__init__.py` — MODIFIED: Add simhash_result parameter
- `src/field_check/report/terminal.py` — MODIFIED: Add _render_near_duplicates() section
- `tests/test_simhash.py` — NEW: Tests for SimHash module
- `tests/conftest.py` — MODIFIED: Add near-duplicate test corpus fixture

## Task Details

### Step 1: Wire SimHash into CLI Pipeline

In `src/field_check/cli.py`:

1. Add import: `from field_check.scanner.simhash import detect_near_duplicates`

2. After language/encoding detection block (around line 217), add SimHash step:
   ```python
   # Detect near-duplicates via SimHash
   simhash_result = None
   if text_cache_result and text_cache_result.text_cache:
       with console.status(
           "[bold blue]Detecting near-duplicates...", spinner="dots"
       ) as status:
           def on_simhash(current: int, total: int) -> None:
               status.update(
                   f"[bold blue]Detecting near-duplicates... "
                   f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
               )
           simhash_result = detect_near_duplicates(
               text_cache_result.text_cache,
               threshold=config.simhash_threshold,
               progress_callback=on_simhash,
           )
   ```

3. Pass `simhash_result=simhash_result` to `generate_report()` call.

### Step 2: Update Report Dispatcher

In `src/field_check/report/__init__.py`:

1. Add import: `from field_check.scanner.simhash import SimHashResult`
2. Add parameter: `simhash_result: SimHashResult | None = None`
3. Pass through to `render_terminal_report()`: `simhash_result=simhash_result`

### Step 3: Add Near-Duplicate Report Section

In `src/field_check/report/terminal.py`:

1. Add import: `from field_check.scanner.simhash import SimHashResult`

2. Update `render_terminal_report()` signature to accept `simhash_result: SimHashResult | None = None`

3. Add Section 7 (between Language & Encoding and Size Distribution):
   ```python
   # Section 7: Near-Duplicate Detection
   if simhash_result is not None and sample_result is not None:
       _render_near_duplicates(simhash_result, sample_result, console)
   ```

4. Create `_render_near_duplicates(simhash, sample, console)`:

   **Summary table:**
   - Title: "Near-Duplicate Detection (estimated)"
   - Rows:
     - "Files analyzed" → `simhash.total_analyzed`
     - "Near-duplicate clusters" → `simhash.total_clusters`
     - "Files in clusters" → `simhash.total_files_in_clusters`
     - "Est. corpus near-dup %" → CI using `compute_confidence_interval(files_in_clusters, total_analyzed, population)`
   - Note below table: "Near-duplicates detected via SimHash fingerprinting (threshold: X bits)"

   **Cluster detail table (if clusters exist):**
   - Title: "Top Near-Duplicate Clusters (showing N of M)"
   - Show top 5 clusters sorted by size desc, then similarity desc
   - Columns: Cluster #, Files, Similarity, Paths
   - For each cluster:
     - Show similarity as percentage (e.g., "93.8%")
     - Show file paths (basename only to save space), limit to 5 paths per cluster
     - If more than 5 paths: "... and N more"
   - Use `walk_result.scan_root` to compute relative paths where possible

### Step 4: Create Test File

Create `tests/test_simhash.py` with these test classes:

**TestComputeSimHash (6 tests):**
- `test_deterministic` — same text always produces same hash
- `test_different_texts` — different texts produce different hashes
- `test_similar_texts_close_distance` — near-identical texts have small Hamming distance
- `test_empty_text` — returns 0 or handles gracefully
- `test_short_text` — text under 50 chars still computes (but gets skipped in detect)
- `test_long_text` — large text computes without error

**TestHammingDistance (3 tests):**
- `test_identical` — distance is 0
- `test_completely_different` — distance is 64 for inverted bits
- `test_known_values` — specific bit patterns with known distances

**TestSimilarityScore (2 tests):**
- `test_identical` — score is 1.0
- `test_range` — score between 0.0 and 1.0

**TestDetectNearDuplicates (6 tests):**
- `test_empty_cache` — returns empty result
- `test_no_duplicates` — distinct texts produce no clusters
- `test_near_duplicate_pair` — two similar texts form a cluster
- `test_transitive_clustering` — A≈B, B≈C groups {A,B,C}
- `test_threshold_boundary` — tests at exactly the threshold boundary
- `test_short_text_skipped` — texts <50 chars excluded from analysis
- `test_progress_callback` — callback fires for each file

**TestConfigThreshold (2 tests):**
- `test_default_threshold` — config defaults to 5
- `test_yaml_threshold` — parses simhash.threshold from YAML

### Step 5: Add Test Fixture

In `tests/conftest.py`, add `tmp_neardup_corpus` fixture:
- Create 3 near-duplicate text files (same base text with minor variations: changed a word, added a sentence, removed a sentence)
- Create 2 distinct text files (completely different content)
- All files >100 chars to be above the short-text cutoff

### Step 6: Lint + Full Test Run

- Run `uv run ruff check .` — ensure lint clean
- Run `uv run pytest --cov --cov-fail-under=80` — all tests pass, coverage ≥80%

## Verification
- [ ] `uv run field-check scan <test-corpus> --sampling-rate 1.0` shows Near-Duplicate Detection section
- [ ] Near-duplicate clusters display with file paths and similarity %
- [ ] "estimated" label appears in report title
- [ ] `uv run ruff check .` — lint clean
- [ ] `uv run pytest --cov --cov-fail-under=80` — all pass, coverage ≥80%

## Done When
- SimHash wired into CLI pipeline using text cache
- Terminal report shows Near-Duplicate Detection section with summary + cluster list
- 19+ tests pass covering SimHash, clustering, config, and integration
- Coverage ≥80%

## Notes
- Report section goes between Language & Encoding and Size Distribution (Section 7)
- Cluster paths shown as basenames to keep table compact; full relative paths if within scan_root
- "estimated" label in section title since results are from sampled data (Invariant 4)
- CI displayed for corpus near-dup percentage (Invariant 4)
- The simhash_threshold config key follows same pattern as sampling/pii config sections
