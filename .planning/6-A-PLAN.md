# Phase 6 - Plan A: SimHash Scanner Module + Config Update

## Overview
Create the SimHash near-duplicate detection module with 64-bit fingerprinting, Hamming distance comparison, and union-find clustering. Add `simhash_threshold` to config.

## Prerequisites
- Phase 5 complete (shared text cache available)
- `build_text_cache()` producing `text_cache: dict[str, str]`

## Files to Create/Modify
- `src/field_check/scanner/simhash.py` — NEW: SimHash implementation + clustering
- `src/field_check/config.py` — MODIFIED: Add `simhash_threshold` field

## Task Details

### Step 1: Create `simhash.py` — Core SimHash Algorithm

Create `src/field_check/scanner/simhash.py` with:

**Constants:**
- `DEFAULT_THRESHOLD = 5` (Hamming distance for ~92% similarity)
- `SIMHASH_BITS = 64`
- `_WORD_PATTERN = re.compile(r"\w+")` for tokenization

**Functions:**

1. `_tokenize(text: str) -> list[str]`
   - Lowercase text, split on `_WORD_PATTERN`
   - Generate 3-shingles (sliding window of 3 tokens joined by space)
   - If fewer than 3 tokens, return individual tokens
   - Return list of shingle strings

2. `compute_simhash(text: str) -> int`
   - Tokenize text into shingles via `_tokenize()`
   - Initialize vector of SIMHASH_BITS zeros
   - For each shingle:
     - Hash with `hashlib.md5(shingle.encode("utf-8")).digest()`
     - Convert first 8 bytes to 64-bit int (`int.from_bytes(digest[:8], "big")`)
     - For each bit position 0..63: if bit is set, add 1 to vector[bit], else subtract 1
   - Final fingerprint: bit `i` is 1 if `vector[i] > 0`, else 0
   - Return 64-bit integer

3. `hamming_distance(a: int, b: int) -> int`
   - Return `bin(a ^ b).count("1")`
   - Simple XOR + popcount

4. `similarity_score(a: int, b: int) -> float`
   - Return `1.0 - hamming_distance(a, b) / SIMHASH_BITS`
   - Value between 0.0 and 1.0

### Step 2: Add Union-Find Clustering

5. `_UnionFind` class (internal):
   - `__init__(self)` — `self.parent: dict[str, str] = {}`
   - `find(self, x: str) -> str` — path compression
   - `union(self, x: str, y: str) -> None`
   - `groups(self) -> dict[str, list[str]]` — return root → members mapping

### Step 3: Add Result Dataclasses and Main Analysis Function

**Dataclasses:**

6. `NearDuplicateCluster`:
   - `paths: list[str]`
   - `similarity: float` (average pairwise similarity within cluster)
   - `fingerprints: list[int]`

7. `SimHashResult`:
   - `total_analyzed: int = 0`
   - `total_clusters: int = 0`
   - `total_files_in_clusters: int = 0`
   - `clusters: list[NearDuplicateCluster]`
   - `fingerprints: dict[str, int]` (path → simhash value, for debugging)

8. `detect_near_duplicates(text_cache: dict[str, str], threshold: int = DEFAULT_THRESHOLD, progress_callback: Callable | None = None) -> SimHashResult`
   - Compute SimHash for each file in `text_cache`
   - Pairwise compare all fingerprints (O(n²) is fine for sampled data, typically <500 files)
   - If `hamming_distance(a, b) <= threshold`, union the two paths
   - Build clusters from union-find groups (only groups with 2+ members)
   - Calculate average similarity for each cluster
   - Sort clusters by size descending, then by similarity descending
   - Return `SimHashResult`
   - Skip files with very short text (<50 chars) — too noisy for SimHash

### Step 4: Update Config

In `src/field_check/config.py`:
- Add `simhash_threshold: int = 5` to `FieldCheckConfig` dataclass
- In `load_config()`, parse `simhash` section from YAML:
  ```yaml
  simhash:
    threshold: 5  # Hamming distance (0-64, lower = stricter)
  ```
- Validate: `0 <= threshold <= 64`, clamp to valid range

## Verification
- [ ] `uv run python -c "from field_check.scanner.simhash import compute_simhash, detect_near_duplicates; print('OK')"` — imports work
- [ ] `uv run python -c "from field_check.scanner.simhash import compute_simhash; h = compute_simhash('hello world test'); print(type(h), 0 <= h < 2**64)"` — returns 64-bit int
- [ ] `uv run python -c "from field_check.scanner.simhash import compute_simhash, hamming_distance; a = compute_simhash('the cat sat on the mat in the house'); b = compute_simhash('the cat sat on the mat in the home'); print(hamming_distance(a, b))"` — small distance for similar texts
- [ ] `uv run ruff check src/field_check/scanner/simhash.py src/field_check/config.py` — lint clean

## Done When
- `simhash.py` module exists with `compute_simhash()`, `hamming_distance()`, `detect_near_duplicates()`
- Config has `simhash_threshold` field, parseable from YAML
- All verification commands pass

## Notes
- Using MD5 for token hashing (not security-sensitive, just needs distribution). MD5 is in stdlib and fast.
- 3-shingles capture word context better than individual tokens for document similarity.
- O(n²) pairwise comparison is acceptable since we're working on sampled data (~100-500 files).
- For very large samples, could use bucketing (hamming distance bands) but YAGNI for v1.0.
- Skip files with <50 chars to avoid noise — very short texts produce unreliable fingerprints.
