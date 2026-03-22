# Phase 4 Context

> Implementation decisions captured via /discuss-phase 4

## Phase Overview
PII regex scanning (email, CC, SSN, phone, IP) with Luhn validation, page count distribution, `--show-pii-samples` flag, and custom PII patterns from config.

## Decisions Made

### 1. PII Text Source
**Question:** How should PII scanning get text content to analyze?
**Decision:** Expanded hybrid approach — re-read PDFs/DOCXes for text extraction, add plain text types (.txt, .csv, .json, .xml) via charset-normalizer encoding detection. Reuses Phase 3's stratified sample (no separate sampling pass).
**Rationale:** Best coverage (all text-bearing file types) + best accuracy (clean extracted text). Phase 3's TextResult doesn't store actual text content, so re-reading is required regardless.

### 2. PII Report Display
**Question:** How should PII results be displayed in the terminal report?
**Decision:** Per-type breakdown — separate mini-table for each PII pattern type showing count, files affected, and confidence interval.
**Rationale:** User wants detailed visibility into each PII category. More screen space but more actionable for data teams.

### 3. Page Count Placement
**Question:** Where should page count distribution appear in the report?
**Decision:** Inside the existing Document Content Analysis section as a sub-section.
**Rationale:** Keeps related document metrics together. Avoids adding yet another top-level section to an already long report.

### 4. Custom PII Patterns
**Question:** Should custom PII patterns from .field-check.yaml be supported in this phase?
**Decision:** Implement now — support `pii.custom_patterns` in config with name + regex fields per the spec's YAML format.
**Rationale:** Spec already defines the format. Small incremental effort. Adds immediate value for teams with domain-specific PII patterns.

### 5. Luhn Validation
**Question:** Full Luhn checksum or digit count + format only for credit card detection?
**Decision:** Full Luhn checksum on every CC candidate.
**Rationale:** Significantly reduces false positives (spec targets 15-25% FP with Luhn). Negligible performance cost on sampled data.

### 6. PII Samples Warning
**Question:** How to present the privacy warning when --show-pii-samples is used?
**Decision:** Yellow warning banner in the report output (Rich Panel with yellow border). Non-blocking — no interactive confirmation prompt.
**Rationale:** Visible warning without breaking non-interactive/CI usage. The flag itself is opt-in, so the user has already made a conscious choice.

## Locked Decisions
These decisions are now locked for planning:
- Expanded hybrid text source (re-read PDFs/DOCXes + plain text types from same sample)
- Per-type breakdown display for PII results
- Page count distribution inside Document Content Analysis section
- Custom PII patterns supported via pii.custom_patterns config
- Full Luhn checksum for CC validation
- Yellow warning banner (non-blocking) for --show-pii-samples

## Open Questions
- None
