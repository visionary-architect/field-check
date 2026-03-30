# Project State

> This file tracks decisions, blockers, and progress across AI sessions.
> The AI reads this at the start of each session.

---

## Current Focus

**Status:** v0.3 feature development — 4 new corpus intelligence features
**Last Commit:** 82bdabf
**Branch:** `fix/third-pass-2026-review` (PR #1 open)
**Next Step:** Plan and implement v0.3 features (Cost Estimator, RAG Readiness, Multimodal, Provenance)

---

## Current Phase

**Milestone:** v0.3
**Phase:** Pre-planning — v0.3 roadmap locked in, implementation not yet started
**Previous Phase:** Post-Phase 8 — third-pass 2026 review complete

### Strategic Shift: CLI-First (2026-03-22)

Desktop GUI (Tauri) deferred due to code signing costs ($300-500/year for
Apple + Windows certificates). The CLI is the primary distribution channel.

**Rationale:**
- Target audience (ML engineers, data teams) lives in the terminal
- `pip install field-check` is zero-friction — no signing, no installers
- GUI sidecar code is maintained and tested, can be revisited later
- Future visual option: `field-check serve` (localhost web UI, no signing)

**What stays:** `gui/` directory remains in repo, sidecar IPC is tested
**What's deferred:** Tauri bundling, platform installers, code signing

---

## Recent Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-03 | Using visionary_template_1 v1.2 | Structured workflow for AI-augmented development |
| 2026-03-03 | Python 3.11+ minimum | Modern type hints, performance improvements |
| 2026-03-03 | UV for dev, pip/pipx for users | UV fast for dev, pip universal for install |
| 2026-03-03 | Click over argparse/typer | Mature, well-documented, composable |
| 2026-03-03 | filetype over python-magic | Pure Python, no C dependency, cross-platform |
| 2026-03-03 | Process pool over thread pool | Crash isolation — one bad file can't kill scan |
| 2026-03-03 | Apache 2.0 license | Commercial forks must preserve attribution |
| 2026-03-05 | ProcessPoolExecutor for text extraction | Crash isolation with auto-restart, per-file timeout |
| 2026-03-05 | Single-pass text extraction | Open file once for text + metadata + scanned detection |
| 2026-03-05 | page.chars for scanned PDF detection | Most accurate method via pdfplumber char objects |
| 2026-03-05 | Combined image-heavy classification | chars/page primary + text/size ratio secondary |
| 2026-03-05 | Per-field metadata reporting | Most actionable for data teams |
| 2026-03-05 | Sampling config in FieldCheckConfig | Single config object via .field-check.yaml |
| 2026-03-05 | Expanded hybrid PII text source | Re-read PDFs/DOCXes + plain text types from same sample |
| 2026-03-05 | Per-type PII breakdown display | Separate mini-table per PII pattern type with CIs |
| 2026-03-05 | Page counts inside Document Content Analysis | Keeps related document metrics together |
| 2026-03-05 | Custom PII patterns in Phase 4 | pii.custom_patterns in .field-check.yaml config |
| 2026-03-05 | Full Luhn checksum for CC detection | Reduces FP rate to 15-25% per spec |
| 2026-03-05 | Yellow warning banner for --show-pii-samples | Non-blocking, doesn't break CI usage |
| 2026-03-05 | Shared text cache for PII + language + encoding | Extract once, pass to all scanners |
| 2026-03-05 | 7 core Latin-script stop-word profiles | EN, ES, FR, DE, PT, IT, NL + Unicode script detection |
| 2026-03-05 | Encoding detection on plain text types only | PDF/DOCX handle encoding internally |
| 2026-03-05 | Combined Language & Encoding report section | Two sub-tables, reduces visual clutter |
| 2026-03-05 | Build SimHash from scratch (no new dep) | Simple algorithm, consistent with zero-dep core philosophy |
| 2026-03-05 | Default 5-bit Hamming threshold, configurable | Best middle-ground for document corpora |
| 2026-03-05 | Summary stats + top cluster list in report | Most actionable format for users |
| 2026-03-05 | SimHash uses shared text cache | No additional file I/O, reuse extracted text |
| 2026-03-05 | HTML report with embedded Chart.js | Polished interactive charts, self-contained |
| 2026-03-05 | JSON: summary + per-file data array | Enables CI/CD processing and diff tracking |
| 2026-03-05 | Conservative CI thresholds (PII 5%, dupes 10%, corrupt 1%) | Matches spec, configurable via YAML |
| 2026-03-05 | Auto-generate output filenames in CWD | Convenient defaults, --output overrides |
| 2026-03-05 | Comprehensive showcase README | Primary marketing surface for PyPI |
| 2026-03-05 | CI on PRs to main only | Saves Actions minutes, low noise |
| 2026-03-05 | Publish as v0.1.0 alpha | Bump to 1.0.0 when cloud connectors land |
| 2026-03-22 | CLI-first, defer desktop GUI | Code signing costs ($300-500/yr), target audience prefers CLI |
| 2026-03-22 | Keep sidecar code maintained | IPC architecture ready if GUI revisited or web UI added |

---

## Open Questions / Blockers

- [ ] None yet

---

## Session Log

<!-- New sessions are added at the top -->

### 2026-03-23 (session 31)
- Third-pass 2026 review: 17 files changed (CVE patches, API updates, new PII patterns)
- Low-priority fixes: BLAKE3 for SimHash, IPv6/crypto wallet PII, DEFF log-transform
- Brainstormed + validated 10 feature ideas against 2026 data (4 parallel research agents)
- Locked in v0.3 roadmap: LLM Cost Estimator, RAG Readiness, Multimodal Inventory, Document Provenance
- Committed as 5ff3f62, 82bdabf
- Paused: ready to plan v0.3 implementation

### 2026-03-22 (session 30)
- Fixed sidecar hang: `check_corruption()` hardcoded ProcessPoolExecutor, causing Windows pipe hang
- Threaded `executor_class` through corruption.py → pipeline.py (completes H6 fix)
- All 11 sidecar integration tests now pass (previously 2 failed with timeouts)
- Full test suite: 0 failures, 12 expected skips
- Strategic decision: CLI-first, defer Tauri GUI due to code signing costs
- Committed as 0da61a0

### 2026-03-06 (session 29)
- Continued comprehensive review fix-up from compacted session
- Fixed 4 test failures: Faiss numpy dependency, encoding mock patching, semantic dedup module reload pollution
- All 553 tests pass (12 skips), coverage 94.25%
- Committed as 99068a6
- See DEVLOG.md for full session details

### 2026-03-06 (session 28)
- Comprehensive end-to-end review (5 parallel agents) found ~30 findings
- Implemented all fixes across 5 batches: bug fixes, INVARIANT 5, CLI, performance, tests
- Created tests/test_mock_deps.py with 51 mock-based tests for optional deps
- Coverage: 88.77% → 94.25%

### 2026-03-06 (session 27)
- Implemented all 20 upgrade items from deep research plan
- Second-pass review + fixes committed (3d0923e)

### 2026-03-05 (session 26)
- Executed `/execute-phase 8` — both plans complete
  - Plan A: README rewrite + py.typed marker (e825db2)
  - Plan B: GitHub Actions CI + PyPI publish workflows (a28a52b)
- Next: `/verify-work 8`

### 2026-03-05 (session 25)
- Ran `/plan-phase 8` — created 2 atomic task plans
  - Plan A: README rewrite + package polish (README.md, py.typed, pyproject.toml)
  - Plan B: GitHub Actions CI + publish workflows (.github/workflows/)
- Next: `/execute-phase 8`

### 2026-03-05 (session 24)
- Ran `/discuss-phase 8` — captured 3 implementation decisions
  - README: Comprehensive showcase with badges, terminal output, usage examples
  - CI: PRs to main only (test + lint)
  - Version: 0.1.0 alpha
- Next: `/plan-phase 8`

### 2026-03-05 (session 23)
- Ran `/verify-work 7` — 6/6 UAT tests passed
  - JSON export: valid structure with summary + per-file data ✓
  - CSV export: 10-column inventory, duplicate flags, PII types ✓
  - HTML report: ~221KB self-contained, Chart.js charts, 9 sections ✓
  - CI exit codes: default thresholds→exit 1, raised→exit 0, clean→exit 0 ✓
  - PII Invariant 3: zero content leaks across all formats ✓
  - Regression: all terminal report sections intact ✓
- Phase 7 complete. Next: `/discuss-phase 8`

### 2026-03-05 (session 22)
- Executed `/execute-phase 7` — all 3 plans complete
  - Plan A: JSON + CSV export modules + CI exit codes + config (53ab8d2)
  - Plan B: HTML report with Chart.js, self-contained ~220KB (83d0b62)
  - Plan C: CLI exit codes + 29 tests — 203 passed, 84.13% coverage (778c01e)
- Next: `/verify-work 7`

### 2026-03-05 (session 21)
- Ran `/plan-phase 7` — created 3 atomic task plans
  - Plan A: JSON + CSV export modules + CI exit codes + config (4 files)
  - Plan B: HTML report with Chart.js (3 files)
  - Plan C: CLI integration + tests (3 files)
- Next: `/execute-phase 7`

### 2026-03-05 (session 20)
- Ran `/discuss-phase 7` — captured 4 implementation decisions
  - HTML: Chart.js embedded, self-contained inline CSS + JS
  - JSON: Summary + per-file data array, pretty-printed
  - CI: Conservative defaults (PII 5%, dupes 10%, corrupt 1%), configurable
  - Output: Auto-named in CWD, --output overrides
- Next: `/plan-phase 7`

### 2026-03-05 (session 19)
- Ran `/verify-work 6` — 6/6 UAT tests passed
  - Near-duplicate detection section in report ✓
  - Cluster display with paths and similarity % ✓
  - Estimated label + CIs (Invariant 4) ✓
  - Configurable threshold via .field-check.yaml (tested 5, 10, 20 bits) ✓
  - Shared text cache integration with PII ✓
  - Regression — all existing report sections intact ✓
- Phase 6 complete. Next: `/discuss-phase 7`

### 2026-03-05 (session 18)
- Ran `/execute-phase 6` — both plans complete
  - Plan A: SimHash scanner module + config update (94fa2a6)
  - Plan B: CLI + report integration + tests — 170 passed, 82.7% coverage (ac4b065)
- Next: `/verify-work 6`

### 2026-03-05 (session 17)
- Ran `/discuss-phase 6` — captured 4 implementation decisions
  - Build SimHash from scratch (hashlib + 64-bit fingerprint)
  - Default 5-bit Hamming threshold, configurable via simhash_threshold
  - Summary stats + top cluster list with file paths
  - SimHash uses shared text cache
- Ran `/plan-phase 6` — created 2 atomic task plans
- Next: `/execute-phase 6`

### 2026-03-05 (session 16)
- Ran `/verify-work 5` — 6/6 UAT tests passed
  - Found and fixed encoding normalization bug: `utf_8` vs `utf-8` (e978883)
  - Verified: Language distribution, encoding distribution, CIs, multi-language, PII with cache, regression
- Phase 5 complete. Next: `/discuss-phase 6`

### 2026-03-05 (session 15)
- Ran `/plan-phase 5` — created 2 atomic task plans
- Executed `/execute-phase 5` — both plans complete
  - Plan A: Language + encoding scanner modules + shared text cache (c3eaee4)
  - Plan B: CLI + report integration + tests — 147 passed, 82% coverage (1c857dc)
- Next: `/verify-work 5`

### 2026-03-05 (session 14)
- Ran `/discuss-phase 5` — captured 4 implementation decisions
  - Shared text cache (extract once, pass to PII + language + encoding)
  - 7 core Latin-script stop-word profiles + Unicode script detection
  - Encoding detection on plain text types only
  - Combined Language & Encoding report section
- Next: `/plan-phase 5`

### 2026-03-05 (session 13)
- Ran `/verify-work 4` — 8/8 UAT tests passed
  - Verified: PII Risk Indicators, page count distribution, --show-pii-samples, Invariant 3 (no PII content), custom patterns, CIs, crash isolation, regression
- Phase 4 complete. Next: `/discuss-phase 5`

### 2026-03-05 (session 12)
- Executed `/execute-phase 4` — both plans complete
  - Plan A: PII scanner module + page count distribution (358b9aa)
  - Plan B: CLI + report integration + tests — 107 passed, 82% coverage (159bf13)
- Next: `/verify-work 4`

### 2026-03-05 (session 11)
- Ran `/plan-phase 4` — created 2 atomic task plans
  - Plan A: PII scanner module + page count distribution (pii.py, config.py, text.py)
  - Plan B: CLI + report integration + tests (cli.py, report/, test_pii.py, conftest.py)
- Next: `/execute-phase 4`

### 2026-03-05 (session 10)
- Ran `/discuss-phase 4` — captured 6 implementation decisions
  - Expanded hybrid PII text source (re-read + plain text types)
  - Per-type PII breakdown display
  - Page counts inside Document Content Analysis
  - Custom PII patterns implemented now
  - Full Luhn checksum for CC detection
  - Yellow warning banner for --show-pii-samples
- Next: `/plan-phase 4`

### 2026-03-05 (session 9)
- Ran `/verify-work 3` — 7/7 UAT tests passed
  - Found and fixed bug: scanned detection counted DOCXes as "native" (f7f04a3)
  - Verified: Document Content Analysis, scanned detection, CIs, --sampling-rate, crash isolation, metadata, regression
- Phase 3 complete. Next: `/discuss-phase 4`

### 2026-03-05 (session 8)
- Executed `/execute-phase 3` — both plans complete
  - Plan A: Sampling framework + text extraction pipeline (f7a60e0)
  - Plan B: CLI + report integration + tests — 93 passed, 86% coverage (d89d0eb)
- Next: `/verify-work 3`

### 2026-03-05 (session 7)
- Ran `/plan-phase 3` — created 2 atomic task plans
  - Plan A: Sampling framework + text extraction pipeline (config.py, inventory.py, sampling.py, text.py)
  - Plan B: CLI + report integration + tests (cli.py, report/, conftest.py, test_sampling.py, test_text.py)
- Next: `/execute-phase 3` to build

### 2026-03-05 (session 6)
- Ran `/discuss-phase 3` — captured 6 implementation decisions
  - ProcessPoolExecutor for crash isolation
  - Single-pass text extraction
  - page.chars for scanned PDF detection
  - Combined chars/page + size ratio for image-heavy
  - Per-field metadata completeness reporting
  - Sampling config in FieldCheckConfig
- Next: `/plan-phase 3`

### 2026-03-05 (session 5)
- Executed `/execute-phase 2` — both plans complete
  - Plan A: BLAKE3 dedup scanner + corruption detector (64d0634)
  - Plan B: Report integration + tests — 69 passed, 85% coverage (7c86bd3)
- Verified `/verify-work 2` — 7/7 UAT tests passed
- Phase 2 complete. Next: `/discuss-phase 3`

### 2026-03-03 (session 4)
- Ran `/plan-phase 2` — created 2 atomic task plans
  - Plan A: BLAKE3 dedup scanner + corruption/encrypted/empty detection (scanner/dedup.py, scanner/corruption.py)
  - Plan B: Report integration + tests (cli.py, report/, tests/test_dedup.py, tests/test_corruption.py)
- Next: `/execute-phase 2` to build

### 2026-03-03 (session 3)
- Executed `/execute-phase 1` — all 3 plans complete
  - Plan A: CLI + config + file walker (35e2c0c)
  - Plan B: Inventory analysis + terminal report (6ef4a59)
  - Plan C: Test suite — 47 passed, 84% coverage (3a28f10)
- Next: `/verify-work 1`

### 2026-03-03 (session 2)
- Ran `/plan-phase 1` — created 3 atomic task plans
  - Plan A: CLI entry point + config loader + file walker (cli.py, config.py, scanner/__init__.py)
  - Plan B: Inventory analysis + terminal report (scanner/inventory.py, report/terminal.py)
  - Plan C: Test suite + fixtures (tests/, 80%+ coverage)
- Next: `/execute-phase 1` to build

### 2026-03-03
- Project initialized from visionary_template_1 v1.2
- Filled in: CLAUDE.md, PROJECT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md, DEVLOG.md
- Copied SPEC.md into docs/
- Created pyproject.toml and basic directory structure
- Next: `/plan-phase 1` for package skeleton

---

## Handoff Notes

> Used by `/pause-work` and `/resume-work` for session continuity.

**Last Updated:** 2026-03-23 14:00
**Session Ended:** v0.3 roadmap locked in, pausing before implementation planning

### In Progress
None — roadmap planning complete, implementation not yet started.

### Resume Point
v0.3 roadmap is locked in with 4 features. Next step is to plan implementation.
Branch `fix/third-pass-2026-review` has PR #1 open — merge to main before starting v0.3.

### Task State

**In Progress:** None
**Pending:** v0.3 feature implementation (4 features)
**Blocked:** None

### Next Steps
1. Merge PR #1 (`fix/third-pass-2026-review`) to main
2. Plan v0.3 implementation — decide phase structure for the 4 features
3. Implement features (all build on existing scan data, minimal new deps):
   - **LLM Cost Estimator** — token counting + cost projection (zero deps)
   - **RAG Readiness Score** — chunk-ability metrics from extracted text (zero deps)
   - **Multimodal Content Inventory** — content type counting via pdfminer.six (existing dep)
   - **Document Provenance Metadata** — XMP/DocInfo extraction via pikepdf (optional dep)
4. Update reports (terminal, HTML, JSON, CSV) with new sections
5. Update version to v0.3.0 and release

### Uncommitted Work
- STATE.md, DEVLOG.md (this handoff update)

### Context to Remember
- 681 tests passing, 91.7% coverage, 12 skips
- Third-pass review applied: pdfplumber CVE fix, fast-langdetect 1.0 API, BLAKE3 SimHash, new PII patterns
- All 4 v0.3 features validated against 2026 web research — see memory/MEMORY.md for details
- Key research: 4-chars-per-token heuristic (10-15% accuracy), pdfminer.six typed layout objects, pikepdf XMP provenance
- Archived ideas documented in memory/MEMORY.md for future reference
- Target <50MB installed size for core (all 4 features are zero or minimal new deps)

### Known Remaining Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| text_workers.py coverage at 80% | low | Optional dep import error paths |
| terminal_content.py lines 493-523 uncovered | low | Cloud/advanced report sections |

### VPS / Production Status

Not applicable — this is a CLI tool distributed via PyPI.

---

*This file is managed by the workflow commands.*
