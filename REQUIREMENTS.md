# Requirements

---

## v1.0 - Must Have

Critical features for the initial PyPI release:

| ID | Requirement | Phase | Status |
|----|-------------|-------|--------|
| M1 | Package skeleton — pyproject.toml, Click CLI, `pip install -e .` working | 1 | [ ] |
| M2 | Local folder scanning with file walker (respects .field-check.yaml excludes) | 1 | [ ] |
| M3 | File inventory — count, types (magic-byte), sizes, directory structure | 1 | [ ] |
| M4 | Basic terminal report via Rich | 1 | [ ] |
| M5 | BLAKE3 exact dedup (full corpus) | 2 | [ ] |
| M6 | Corrupt/encrypted/empty file detection | 2 | [ ] |
| M7 | Stratified sampling framework (10% default, min 30 per type) | 3 | [ ] |
| M8 | Text extraction pipeline (pdfplumber, python-docx) | 3 | [ ] |
| M9 | Scanned vs native PDF detection | 3 | [ ] |
| M10 | PII regex scanning (email, CC, SSN, phone, IP) with Luhn validation | 4 | [ ] |
| M11 | Page count distribution | 4 | [ ] |
| M12 | Language detection (Unicode script + stop-words) | 5 | [ ] |
| M13 | Encoding detection (charset-normalizer) | 5 | [ ] |
| M14 | SimHash near-dedup (sampled, labeled as estimated) | 6 | [ ] |
| M15 | HTML report (Jinja2, self-contained) | 7 | [ ] |
| M16 | JSON export | 7 | [ ] |
| M17 | CSV export (file-level inventory with all flags) | 7 | [ ] |
| M18 | CI exit codes (0 = clean, 1 = critical findings, 2 = scan failed) | 7 | [ ] |
| M19 | PyPI publish + README + GitHub Actions CI | 8 | [ ] |

---

## v1.0 - Should Have

Important features to include if possible:

| ID | Requirement | Phase | Status |
|----|-------------|-------|--------|
| S1 | .field-check.yaml config file support (excludes, sampling rate, PII custom patterns, thresholds) | 1 | [ ] |
| S2 | Symlink loop detection (inode tracking) | 1 | [ ] |
| S3 | Windows 260-char path limit handling | 1 | [ ] |
| S4 | File age distribution (mtime/ctime) | 1 | [ ] |
| S5 | Image-heavy vs text-heavy classification | 3 | [ ] |
| S6 | Metadata completeness check (title, author, creation date) | 3 | [ ] |
| S7 | `--show-pii-samples` flag (with warning) | 4 | [ ] |
| S8 | `--metadata-only` mode for cloud scans | 9 | [ ] |
| S9 | `--dry-run` for cloud scans | 9 | [ ] |
| S10 | Confidence intervals displayed on all sampled analyses | 3 | [ ] |

---

## v1.1 - Cloud Connectors

| ID | Requirement | Phase | Status |
|----|-------------|-------|--------|
| C1 | S3 connector with cost estimation + confirmation | 9 | [ ] |
| C2 | GCS connector | 10 | [ ] |
| C3 | Azure Blob connector | 10 | [ ] |
| C4 | `--yes` flag to skip cloud scan confirmation | 9 | [ ] |

---

## v2.0 - Future

Features planned for future versions:

| ID | Requirement | Notes |
|----|-------------|-------|
| F1 | `field-check upgrade` command | Generate Field pipeline config from scan results |
| F2 | Opt-in cloud dashboard | Metadata-only report to Field-hosted dashboard (email capture) |
| F3 | Tracking over time | Compare scan results across runs |
| F4 | Custom PII recognizer plugins | Load user-defined pattern modules |
| F5 | SQLite fallback for >1M file corpora | Disk-backed storage for hash maps |
| F6 | Demo GIF in README | Table stakes for GitHub virality |

---

## Out of Scope

Features explicitly NOT being built:

- **File processing/transformation** — diagnosis only, never modify
- **OCR execution** — only detect scanned PDFs, not fix them
- **PII redaction** — only flag risk indicators
- **Database/API/email scanning** — files and object storage only
- **Paid features** — fully free, Apache 2.0

---

*Spec: See docs/SPEC.md for full technical specification.*
