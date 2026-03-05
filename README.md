# Field Check

**Scan your document corpus and get a health report before processing.**

[![PyPI](https://img.shields.io/pypi/v/field-check)](https://pypi.org/project/field-check/)
[![Python](https://img.shields.io/pypi/pyversions/field-check)](https://pypi.org/project/field-check/)
[![License](https://img.shields.io/github/license/usefield/field-check)](LICENSE)

Field Check is a free, open-source CLI tool that scans a document corpus and generates a comprehensive health report — file inventory, duplicates, corruption, PII risk indicators, language distribution, encoding issues, near-duplicates, and more. Know exactly what's in your data before feeding it into RAG pipelines, embedding models, or batch AI processing.

## What It Does

Point it at a folder. Get a full diagnostic in seconds.

```console
$ field-check scan ./my-corpus/

+------------- Field Check — Document Corpus Health Report ---------------+
| Scan path:  /home/user/my-corpus                                       |
| Duration:   1.2s                                                        |
| Files:      2,847                                                       |
| Total size: 1.4 GB                                                      |
+-------------------------------------------------------------------------+
              File Type Distribution
+--------------------------------------------------------+
| Type              | Count |     % | Total Size | Avg   |
|-------------------+-------+-------+------------+-------|
| application/pdf   | 1,203 | 42.3% |    892 MB  | 742KB |
| text/plain        |   891 | 31.3% |    156 MB  | 175KB |
| application/msword|   412 | 14.5% |    287 MB  | 697KB |
| text/csv          |   341 | 12.0% |     65 MB  | 191KB |
+--------------------------------------------------------+

      Duplicate Detection
+-----------------------------+
| Metric           |    Value |
|------------------+----------|
| Unique files     |    2,534 |
| Duplicate groups |       98 |
| Duplicate files  |      313 |
| Wasted space     |   142 MB |
| Duplicate %      |    11.0% |
+-----------------------------+

       PII Risk Indicators
+-------------------------------------+
| Files scanned for PII     |     285 |
| Files with PII indicators |      47 |
+-------------------------------------+
  Email: 23 files (8.1%, 95% CI: 5.2–12.0%)
  SSN:    5 files (1.8%, 95% CI: 0.6– 4.1%)
  Phone: 12 files (4.2%, 95% CI: 2.2– 7.3%)

      Near-Duplicate Detection (estimated)
+----------------------------------------------+
| Near-duplicate clusters |                 31 |
| Files in clusters       |                 89 |
| Est. corpus near-dup %  | 3.1% (2.0–4.7%)   |
+----------------------------------------------+

Field Check v0.1.0 — All processing local. No data transmitted.
```

## Install

```bash
pip install field-check
```

Or with [pipx](https://pipx.pypa.io/) for isolated installs:

```bash
pipx install field-check
```

**Requires Python 3.11+**

## Usage

### Basic scan

```bash
field-check scan ./my-documents/
```

### Export formats

```bash
# Interactive HTML report with charts
field-check scan ./corpus/ --format html

# Machine-readable JSON (for CI/CD pipelines)
field-check scan ./corpus/ --format json

# CSV inventory (one row per file)
field-check scan ./corpus/ --format csv -o inventory.csv
```

### Tuning

```bash
# Lower sampling rate for very large corpora
field-check scan ./large-corpus/ --sampling-rate 0.05

# Exclude patterns
field-check scan . --exclude "*.log" --exclude "node_modules"

# Show PII matched content (WARNING: exposes sensitive data)
field-check scan ./corpus/ --show-pii-samples
```

## What It Scans

| Feature | Method | Scope |
|---------|--------|-------|
| **File inventory** | Magic-byte detection via filetype | Full corpus |
| **Exact duplicates** | BLAKE3 content hashing | Full corpus |
| **Corrupt/encrypted/empty** | Header validation + structure checks | Full corpus |
| **PII risk indicators** | Regex patterns (email, CC, SSN, phone, IP) | Sampled (10%) |
| **Language detection** | Unicode script analysis + stop-word matching | Sampled (10%) |
| **Encoding detection** | charset-normalizer | Sampled (10%) |
| **Near-duplicates** | SimHash fingerprinting | Sampled (10%) |
| **Scanned vs native PDFs** | Text layer presence check | Sampled (10%) |
| **Size/age distribution** | File metadata | Full corpus |
| **Directory structure** | Depth/breadth analysis | Full corpus |

Sampled analyses include 95% confidence intervals. No bare point estimates.

## Configuration

Create a `.field-check.yaml` in your corpus directory:

```yaml
# Exclude patterns (glob syntax)
exclude:
  - "*.log"
  - ".git"
  - "node_modules"
  - "__pycache__"

# Sampling rate for content analysis (0.0–1.0)
sampling_rate: 0.10

# SimHash near-duplicate threshold (Hamming distance in bits)
simhash_threshold: 5

# CI exit code thresholds (fraction, not percentage)
thresholds:
  pii_critical: 0.05        # >= 5% files with PII → exit 1
  duplicate_critical: 0.10   # >= 10% exact duplicates → exit 1
  corrupt_critical: 0.01     # >= 1% corrupt files → exit 1
```

## CI/CD Integration

Field Check returns meaningful exit codes for automation:

| Exit Code | Meaning |
|-----------|---------|
| **0** | Clean — no critical findings |
| **1** | Critical findings detected (thresholds exceeded) |
| **2** | Scan failed (invalid path, permissions, etc.) |

```yaml
# GitHub Actions example
- name: Check corpus health
  run: field-check scan ./data/ --format json -o report.json

# GitLab CI example
corpus-check:
  script:
    - field-check scan ./data/ --format json -o report.json
  artifacts:
    paths: [report.json]
```

## Output Formats

| Format | Flag | Description |
|--------|------|-------------|
| **Terminal** | `--format terminal` | Rich tables with color (default) |
| **HTML** | `--format html` | Self-contained report with interactive Chart.js charts |
| **JSON** | `--format json` | Structured data with summary + per-file array |
| **CSV** | `--format csv` | File-level inventory, one row per file |

## Privacy

**All processing is local.** Field Check never transmits your data. No telemetry, no network calls, no cloud dependencies (unless you explicitly use cloud connectors). PII scanning shows counts and pattern types only — matched content is never displayed unless you explicitly pass `--show-pii-samples`.

## License

[Apache 2.0](LICENSE)

## Links

- [PyPI](https://pypi.org/project/field-check/)
- [GitHub](https://github.com/usefield/field-check)
- [Field](https://usefield.co)
