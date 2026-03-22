# Field Check

> "What's actually in my documents, and what will go wrong when I process them?"

---

## Vision

**What:** A free, open-source CLI tool that scans a document corpus and generates a comprehensive health report — file inventory, duplicates, corruption, PII risk indicators, language distribution, encoding issues, scanned vs native PDFs, and more.

**Why:** Every existing tool (Docling, Unstructured, RAGFlow) answers "how do I process my documents?" Nobody answers "what's in my documents, and what will go wrong when I process them?" The closest alternative today is cobbling together Apache Tika + Presidio + custom dedup scripts. Nobody has packaged this.

**For Whom:** ML engineers, data teams, and anyone preparing document corpora for RAG pipelines, embedding, transcription, or batch AI processing. Secondary audience: compliance teams who need PII exposure assessments.

---

## Goals

1. **Be the diagnostic standard** — the tool people run before they process anything
2. **Zero friction** — `pip install field-check && field-check scan ./docs/` in under 60 seconds
3. **Honest reporting** — confidence intervals on sampled data, explicit FP rates on PII
4. **Build Field audience** — every finding links to the Field capability that addresses it
5. **Earn trust** — fully local, no telemetry, Apache 2.0 licensed

---

## Out of Scope

- **Processing, transforming, or fixing files** — diagnosis only
- **Text extraction for the user** — only samples for analysis
- **Adding OCR to scanned PDFs** — only detects them
- **Deleting duplicates** — only identifies them
- **Redacting PII** — only flags risk indicators
- **Scanning databases, APIs, or email** — files and cloud object storage only
- **Paid features or freemium** — fully free, forever

---

## Constraints

- **Install size:** <50MB for core (no cloud extras)
- **Scan time:** 3-10 minutes for 50K documents
- **No C dependencies in core** — filetype (pure Python) over libmagic
- **Python 3.11+** — minimum version
- **Process pool isolation** — one bad file can't kill the scan
- **Memory:** Must handle 1M+ file corpora (SQLite fallback for >1M files)

---

## Success Criteria

- [ ] `pip install field-check` works on Linux, macOS, Windows
- [ ] `field-check scan ./path/` produces terminal report in <10 min for 50K files
- [ ] HTML report is self-contained (no external assets), shareable
- [ ] JSON/CSV export works for CI/CD integration
- [ ] Exit code 1 on critical findings (PII, high duplication)
- [ ] Cloud scan (S3) works with cost estimation and confirmation
- [ ] 80% test coverage
- [ ] Published on PyPI

---

*Spec: See docs/SPEC.md for full technical specification.*
