# Phase 5 Context

> Implementation decisions captured via /discuss-phase 5

## Phase Overview
Language detection via Unicode script ranges + stop-word profiles, encoding detection via charset-normalizer, and terminal report integration. Both analyses run on the stratified sample from Phase 3.

## Decisions Made

### 1. Text Source for Language + Encoding Analysis
**Question:** How should language/encoding analysis get its text content, given that PII scanner already re-reads files?
**Decision:** Shared text cache — extract text once in a shared step after sampling, cache it in a dict mapping file path to extracted text, then pass to PII, language, and encoding scanners. Avoids reading each file 3x.
**Rationale:** Highest quality (all scanners see identical text), most efficient (single read per file), and better testability (pure functions on text input).

### 2. Language Stop-Word Profiles
**Question:** Which languages should have stop-word profiles for disambiguation within Latin script?
**Decision:** 7 core languages — English, Spanish, French, German, Portuguese, Italian, Dutch. CJK, Arabic, Cyrillic, Devanagari, etc. identified by Unicode script alone.
**Rationale:** Covers the most common Latin-script languages in document corpora. Matches the spec's "7 stop-word profiles" reference. Non-Latin scripts don't need stop-word disambiguation.

### 3. Encoding Detection Scope
**Question:** Which files should encoding detection analyze?
**Decision:** Plain text types only — .txt, .csv, .json, .xml, and other text/* MIME types. PDFs and DOCXes are skipped since pdfplumber and python-docx handle their internal encoding.
**Rationale:** Encoding issues only matter for plain text files where the encoding is unknown. PDF/DOCX encoding results would be meaningless noise.

### 4. Report Placement and Format
**Question:** How should language and encoding results be displayed in the terminal report?
**Decision:** Combined "Language & Encoding" section with two sub-tables: language distribution table and encoding distribution table.
**Rationale:** Keeps related text analysis together, reduces visual clutter vs. two separate top-level sections.

## Locked Decisions
These decisions are now locked for planning:
- Shared text cache (extract once, pass to PII + language + encoding)
- 7 core Latin-script stop-word profiles (EN, ES, FR, DE, PT, IT, NL) + Unicode script detection
- Encoding detection on plain text types only (not PDF/DOCX)
- Combined "Language & Encoding" report section with two sub-tables

## Open Questions
- None
