# Roadmap

---

## Current Milestone: v1.0

---

## Phase 1: Package Skeleton + File Inventory

**Status:** complete
**Focus:** Working CLI that scans a local folder and produces a basic terminal report with file inventory

### Deliverables
- [x] pyproject.toml with Click entry point, all core deps
- [x] `field-check scan <path>` command working
- [x] File walker with .field-check.yaml exclude support
- [x] File inventory: count, types (magic-byte via filetype), sizes
- [x] Directory structure analysis (depth/breadth)
- [x] File age distribution (mtime/ctime)
- [x] Basic Rich terminal report
- [x] Symlink loop detection, permission error handling
- [x] Tests with fixture corpus (84% coverage)

### Requirements Addressed
- M1, M2, M3, M4, S1, S2, S3, S4

---

## Phase 2: Dedup + Corruption Detection

**Status:** complete
**Focus:** BLAKE3 full-corpus dedup and corrupt/encrypted/empty file detection

### Deliverables
- [x] BLAKE3 content hashing for all files
- [x] Exact duplicate detection and reporting
- [x] Corrupt file detection (magic-byte + size validation)
- [x] Encrypted file detection (PDF /Encrypt, ZIP flags)
- [x] Empty/near-empty document detection
- [x] Terminal report updated with dedup + corruption sections

### Requirements Addressed
- M5, M6

---

## Phase 3: Text Extraction + Sampling

**Status:** complete
**Focus:** Stratified sampling framework, text extraction, scanned PDF detection

### Deliverables
- [x] Stratified sampling (10% default, min 30 per type, configurable)
- [x] Confidence interval calculation and display
- [x] PDF text extraction via pdfplumber
- [x] DOCX text extraction via python-docx
- [x] Scanned vs native PDF detection (text layer check)
- [x] Image-heavy vs text-heavy classification
- [x] Metadata completeness check
- [x] Process pool isolation for text extraction

### Requirements Addressed
- M7, M8, M9, S5, S6, S10

---

## Phase 4: PII + Page Analysis

**Status:** complete
**Focus:** PII regex scanning and page count distribution

### Deliverables
- [x] PII regex patterns: email, CC (Luhn), SSN, phone, IP
- [x] PII results as "risk indicators" with expected FP rates
- [x] Page count distribution for PDFs
- [x] `--show-pii-samples` flag with privacy warning
- [x] Terminal report updated with PII + page sections

### Requirements Addressed
- M10, M11, S7

---

## Phase 5: Language + Encoding

**Status:** complete
**Focus:** Language detection and encoding analysis

### Deliverables
- [x] Language detection via Unicode script ranges + stop-word profiles
- [x] Multi-language corpus reporting
- [x] Encoding detection via charset-normalizer
- [x] UTF-8/Latin1/mixed encoding reporting
- [x] Terminal report updated with language + encoding sections

### Requirements Addressed
- M12, M13

---

## Phase 6: Near-Duplicate Detection

**Status:** complete
**Focus:** SimHash-based near-duplicate detection on sampled content

### Deliverables
- [x] SimHash implementation on extracted text
- [x] Near-duplicate clustering with similarity threshold
- [x] Results labeled as "estimated" (sampled)
- [x] Terminal report updated with near-dedup section

### Requirements Addressed
- M14

---

## Phase 7: Export Formats

**Status:** complete
**Focus:** HTML, JSON, and CSV report generation + CI exit codes

### Deliverables
- [x] HTML report via Jinja2 (self-contained, no external assets)
- [x] JSON export (structured, machine-readable)
- [x] CSV export (file-level inventory with all flags)
- [x] `--format` flag (terminal/html/json/csv)
- [x] CI exit codes: 0 clean, 1 critical, 2 failed
- [x] Configurable thresholds for critical findings

### Requirements Addressed
- M15, M16, M17, M18

---

## Phase 8: PyPI Publish

**Status:** complete
**Focus:** Package polish, CI/CD, PyPI release

### Deliverables
- [x] README with usage, examples, demo output
- [x] GitHub Actions CI (test, lint, type-check)
- [x] PyPI publishing workflow
- [ ] `pip install field-check` working from PyPI (requires GitHub repo + PyPI trusted publisher setup)
- [x] License file (Apache 2.0)
- [x] py.typed PEP 561 marker

### Requirements Addressed
- M19

---

## Phase 9: S3 Connector

**Status:** not started
**Focus:** S3 cloud scanning with cost estimation

### Deliverables
- [ ] S3 connector via boto3 (optional extra)
- [ ] Cost estimation before scan (API calls + egress)
- [ ] Confirmation prompt (skippable with `--yes`)
- [ ] `--metadata-only` mode (no content download)
- [ ] `--dry-run` mode

### Requirements Addressed
- C1, C4, S8, S9

---

## Phase 10: GCS + Azure Connectors

**Status:** not started
**Focus:** Google Cloud Storage and Azure Blob connectors

### Deliverables
- [ ] GCS connector (optional extra)
- [ ] Azure Blob connector (optional extra)
- [ ] `field-check[all-cloud]` meta-extra

### Requirements Addressed
- C2, C3

---

## Workflow

For each phase:
1. `/discuss-phase N` - Capture implementation decisions
2. `/plan-phase N` - Create atomic task plans
3. `/execute-phase N` - Implement with progress tracking
4. `/verify-work N` - User acceptance testing

---

*Spec: See docs/SPEC.md for full technical specification.*
