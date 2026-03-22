# Phase 7 Context

> Implementation decisions captured via /discuss-phase 7

## Phase Overview
HTML, JSON, and CSV report generation + CI exit codes. Add `--format` support (already wired as CLI flag) and configurable thresholds for critical findings.

## Decisions Made

### HTML Report Style
**Question:** How should the self-contained HTML report be styled?
**Decision:** Static tables + embedded Chart.js for interactive charts
**Rationale:** More polished UX with hover tooltips and animations. ~65KB file size is acceptable for a diagnostic report. Chart.js vendored inline to keep it self-contained with no external assets.

### JSON Export Scope
**Question:** What data should the JSON export include?
**Decision:** Summary stats + per-file data array
**Rationale:** Per-file data enables CI/CD processing, diff tracking over time, and programmatic analysis. Top-level summary mirrors terminal report sections. Files array includes path, size, type, blake3 hash, is_duplicate, has_pii, language, encoding, etc.

### CI Exit Code Thresholds
**Question:** What default thresholds trigger exit code 1 (critical findings)?
**Decision:** Conservative defaults — PII >= 5%, duplicates >= 10%, corrupt >= 1%
**Rationale:** Matches the spec's YAML example. Configurable via `.field-check.yaml` thresholds section. Exit 1 if ANY threshold exceeded, exit 0 if all below, exit 2 if scan fails.

### Output File Naming
**Question:** How should output files be named when --output is not specified?
**Decision:** Auto-generate in current working directory
**Rationale:** `field-check-report.html`, `field-check-report.json`, `field-check-report.csv` in CWD. Print path to terminal so user knows where the file went. Explicit `--output` overrides.

## Locked Decisions
These decisions are now locked for planning:
- HTML: Chart.js embedded, self-contained, inline CSS + JS
- JSON: Summary + per-file data, pretty-printed
- CSV: File-level inventory with all flags (one row per file)
- CI: Conservative defaults (PII 5%, dupes 10%, corrupt 1%), configurable
- Output: Auto-named in CWD, `--output` overrides

## Open Questions
None
