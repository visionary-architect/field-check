# Field Check — Technical Specification

> "What's actually in my documents, and what will go wrong when I process them?"

## Overview

**Field Check** is a free, open-source CLI tool that scans a document corpus and generates a health report. It runs entirely on the user's machine — no data leaves, no servers, no cost to us.

**Goal:** Build audience and credibility for [Field](https://usefield.co) (distributed document processing network) by becoming the diagnostic tool people run before they process anything.

**Install:** `pip install field-check` or `pipx install field-check`

**Usage:**
```bash
# Local folder
field-check scan ./my-documents/

# S3 bucket (optional extra: pip install field-check[s3])
field-check scan s3://my-bucket/documents/ --profile my-aws-profile

# GCS (optional extra: pip install field-check[gcs])
field-check scan gs://my-bucket/documents/
```

---

## Market Position

**Uncontested space.** Every existing tool (Docling 55k stars, Unstructured 13k, RAGFlow 74k) answers "how do I process my documents?" Nobody answers "what's in my documents, and what will go wrong when I process them?"

The closest alternative today is cobbling together Apache Tika + Presidio + custom dedup scripts. Nobody has packaged this.

**Competitive risk is low.** Docling/Unstructured won't build this — it dilutes their focus. The real risk is someone forking. Defense: ship fast, make the report excellent.

---

## Analyses

### Full Pass (all files)

| Analysis | Method | Notes |
|----------|--------|-------|
| File inventory (count, types, sizes) | Magic-byte detection (filetype lib) | No C dependency |
| Exact duplicates | BLAKE3 content hash | Must hash ALL files — sampling doesn't work for dedup |
| Corrupt/truncated files | Magic-byte + size validation | |
| Encrypted files | PDF /Encrypt + ZIP flag check | |
| Empty/near-empty docs | File size threshold | |
| File age distribution | mtime/ctime | |
| Directory structure analysis | Path depth/breadth | |

### Sampled Pass (stratified ~10% sample, content-level)

| Analysis | Method | Notes |
|----------|--------|-------|
| Scanned vs native PDF | Text layer check (pdfplumber) | 50-200 PDFs/sec — text extraction is the bottleneck |
| PII risk indicators | Regex patterns (SSN, email, CC, phone) | Label as "risk indicators" not "detection" — 30-50% FP rate on SSN |
| Page count distribution | pdfplumber page count | Critical missing analysis — 50K invoices ≠ 500 manuals |
| Language distribution | Unicode script + stop-words | Homebrew approach, no heavy deps |
| Encoding issues | charset-normalizer | UTF-8/Latin1/mixed detection |
| Near-duplicates | SimHash on extracted text | Sampled results labeled as "estimated" |
| Image-heavy vs text-heavy | Text density per page | |
| Metadata completeness | Title, author, creation date | |

### Sampling Strategy

- **Stratified by file type** — proportional sampling within each type, minimum 30 per type (or all if fewer)
- 5,000 samples from 50K corpus gives ~1.4% margin of error at 95% confidence
- **All reports show confidence intervals** — bare point estimates are irresponsible for a diagnostic tool
- Total scan time: **3-10 minutes for 50K documents** depending on format mix and storage backend

---

## Output Formats

| Format | Flag | Use case |
|--------|------|----------|
| Terminal (rich) | default | Interactive use, quick glance |
| HTML | `--format html` | Share with team, email to manager (self-contained, no external assets) |
| JSON | `--format json` | CI/CD, programmatic use, tracking over time |
| CSV | `--format csv` | File-level inventory with all flags (is_duplicate, has_pii, etc.) |

### Exit Codes (for CI)

- `0` — scan complete, no critical findings
- `1` — scan complete, critical findings (PII, high duplicate rate, etc.)
- `2` — scan failed

### Report Content

Each finding links to the relevant Field capability:
- "23% of your PDFs are scanned — these need OCR before embedding. [Field can handle this →]"
- "4.2% duplicate content — processing these wastes money. [Field deduplicates automatically →]"
- "7 languages detected — you need language-aware chunking. [Field routes by language →]"

The report is a diagnostic document that creates urgency for the problems Field solves.

---

## Dependencies

### Core (local-only, target <50MB installed)

| Library | Purpose | Size |
|---------|---------|------|
| click | CLI framework | Small |
| rich | Terminal output + progress bars | ~1MB |
| blake3 | Content hashing (Rust-backed) | ~2MB |
| pdfplumber | PDF text extraction + page count | ~15MB |
| python-docx | DOCX text extraction | ~10MB |
| charset-normalizer | Encoding detection | Small |
| jinja2 | HTML report templates | Small |
| filetype | Magic-byte file type detection (pure Python, no C) | Small |

### Optional Extras

| Extra | Library | Install |
|-------|---------|---------|
| S3 | boto3 (~80MB) | `pip install field-check[s3]` |
| GCS | google-cloud-storage (~30MB) | `pip install field-check[gcs]` |
| Azure | azure-storage-blob (~20MB) | `pip install field-check[azure]` |
| All cloud | All above | `pip install field-check[all-cloud]` |

---

## Cloud Source Scanning

**Cost to us:** Zero. User provides their own credentials, scan runs on their machine, they pay their own egress.

**Cost to the user (example: 50K files, 100KB avg on S3):** ~$0.70-$1.30

**Danger case:** 50K files at 10MB avg = 500GB egress = ~$45

**Required before any cloud scan:**
1. Show estimated API call count and data transfer volume
2. Show estimated cost range
3. Require explicit confirmation (`--yes` to skip prompt)
4. Support `--metadata-only` mode (skips content download)
5. Support `--dry-run` (shows what would be scanned)

---

## Technical Requirements

### Crash Isolation
- Per-file timeout and crash isolation using **process pool** (not thread pool)
- One malformed PDF must not kill the scan
- Count and report permission errors, don't crash

### Memory Management
- For corpora >1M files, use disk-backed storage (SQLite) instead of in-memory dicts
- BLAKE3 hashes: ~64 bytes per file. 1M files = 64MB (fine in memory). 10M files = needs SQLite.

### Edge Cases
- Symlink loop detection (track inode numbers)
- Exclude special files (devices, pipes, sockets)
- Windows 260-char path limit handling
- Graceful permission error handling with summary count

### Privacy
- "Field Check never transmits any data. All processing is local."
- No telemetry. Zero network calls (unless scanning cloud storage).
- PII scan results show counts only, never match content by default
- `--show-pii-samples` flag for manual verification (with warning)
- Report filename should warn against committing to git

---

## PII Regex Patterns (v1)

| Pattern | Regex approach | Expected FP rate |
|---------|---------------|-----------------|
| Email addresses | RFC-5322-ish | Low (5-10%) |
| Credit card numbers | 13-19 digit + Luhn check | Medium (15-25%) |
| SSN (US) | XXX-XX-XXXX | High (30-50%) |
| Phone numbers | Various intl patterns | Very high (40-60%) |
| IP addresses | Dotted quad | Medium |

**Framing:** "PII Risk Indicators (pattern-based, may include false positives)" — not "PII Detection."

Users can contribute additional patterns via config file.

---

## Configuration

`.field-check.yaml` in scanned directory (optional):

```yaml
exclude:
  - "node_modules/"
  - ".git/"
  - "*.tmp"

sampling:
  rate: 0.10  # 10% default
  min_per_type: 30

pii:
  custom_patterns:
    - name: "UK NI Number"
      pattern: "[A-Z]{2}\\d{6}[A-Z]"

thresholds:
  duplicate_warning: 0.10   # warn at 10% duplicates
  pii_critical: 0.05        # critical at 5% PII exposure
```

---

## What Field Check Does NOT Do

- **Does not process, transform, or fix anything** — diagnosis only
- **Does not extract text** for the user — only samples for analysis
- **Does not add OCR** to scanned PDFs
- **Does not delete duplicates**
- **Does not redact PII**
- **Does not scan databases, APIs, or email**

"Field Check diagnoses your corpus. It does not process, transform, or fix anything. For processing, see [Field](https://usefield.co)."

---

## Build Order

1. Package skeleton (`pyproject.toml`, CLI with click, `pip install -e .` working) + local folder scan + file inventory + **basic terminal report**
2. BLAKE3 full-corpus dedup + corrupt/encrypted/empty detection → add to report
3. Text extraction pipeline (pdfplumber, python-docx) + sampling framework + scanned PDF detection
4. PII regex scanning + page count distribution
5. Language + encoding analysis
6. SimHash near-dedup (sampled, labeled as estimated)
7. HTML report (Jinja2) + JSON/CSV export
8. PyPI publish + README + GitHub Actions CI
9. S3 connector (optional extra)
10. GCS + Azure connectors

---

## Reusable from Field Codebase

| Component | Source | What we adapt |
|-----------|--------|---------------|
| Magic-byte detection | `sidecar/preprocessors/format_detect.py` | PDF/ZIP/OOXML/OLE2 signatures, encryption checks |
| Language detection | `sidecar/preprocessors/lang_detect.py` | Unicode script ranges, 7 stop-word profiles |
| PII regex patterns | `sidecar/executors/anonymize.py` | ~30 locale-specific Presidio PatternRecognizers |
| Input validation | `connector/input_sanitization.rs` | File size/type checks, archive bomb thresholds |
| BLAKE3 hashing | `connector/hash_chain.rs` | Hashing approach (Python blake3 package) |

---

## Lead Generation Strategy

(To be refined — not gating the product)

- **The report sells Field.** Each finding links to the Field capability that addresses it.
- **Opt-in cloud dashboard** (future): metadata-only report sent to Field-hosted dashboard for tracking over time. Gives us emails without being sleazy.
- **`field-check upgrade` command** (future): generates a Field pipeline config from scan results.
- **Content marketing:** Blog posts titled "Before you build your RAG pipeline, run this"
- **Community:** r/LocalLLaMA, r/MachineLearning, HackerNews, Docling/Unstructured community posts
- **Demo GIF** in README is table stakes — people share screenshots of good terminal output.

---

## License

Apache 2.0 — commercial forks must preserve attribution.
