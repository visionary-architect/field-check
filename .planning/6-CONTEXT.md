# Phase 6 Context

> Implementation decisions captured via /discuss-phase 6

## Phase Overview
SimHash-based near-duplicate detection on sampled extracted text. Results are labeled as "estimated" since they run on the stratified sample. Terminal report updated with near-duplicate section.

## Decisions Made

### 1. SimHash Implementation Approach
**Question:** Build from scratch or use an existing library?
**Decision:** Build from scratch using hashlib for token hashing. ~60 lines of code.
**Rationale:** SimHash is straightforward to implement. No new dependency, consistent with zero-dependency philosophy for core algorithms (like language detection). Uses stdlib hashlib (MD5) for token hashing, 64-bit fingerprint via weighted bit accumulation.

### 2. Similarity Threshold
**Question:** What Hamming distance threshold for near-duplicate detection?
**Decision:** Default 5 bits out of 64 (~92% similarity), configurable via `.field-check.yaml` as `simhash_threshold`.
**Rationale:** 5 bits is the sweet spot for document corpora — catches template-based variants and minor edits while avoiding false positives from loosely related documents. Configurable so power users can tune sensitivity (lower = stricter, higher = more lenient).

### 3. Report Display Format
**Question:** How to display near-duplicate results?
**Decision:** Summary stats table + top cluster list with file paths and similarity scores.
**Rationale:** Most actionable format — summary gives quick overview, cluster list shows exactly which files are near-duplicates. Shows top 5 clusters by default. Uses union-find for transitive clustering (if A≈B and B≈C, group {A,B,C}).

### 4. Text Source
**Question:** Where does SimHash get its text content?
**Decision:** Use the shared text cache from Phase 5 (`build_text_cache()` output).
**Rationale:** Text already extracted for sampled files by the shared cache. No additional file I/O. Consistent with language/encoding/PII scanners.

## Locked Decisions
These decisions are now locked for planning:
- Build SimHash from scratch (hashlib + 64-bit fingerprint)
- Default threshold: 5 bits Hamming distance, configurable via `simhash_threshold`
- Report: summary stats + top cluster list with file paths
- Union-find clustering for transitive near-duplicate groups
- Text sourced from shared text cache (no additional file I/O)
- Results labeled as "estimated" with confidence intervals (Invariant 4)

## Open Questions
- None
