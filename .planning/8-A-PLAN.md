# Phase 8 - Plan A: README + Package Polish

## Overview
Rewrite README.md as a comprehensive showcase for PyPI, add py.typed marker, and ensure pyproject.toml includes template data.

## Prerequisites
- All core features complete (Phases 1-7)
- LICENSE file exists (Apache 2.0)

## Files to Create/Modify
- `README.md` — REWRITTEN: Comprehensive showcase README
- `src/field_check/py.typed` — NEW: PEP 561 typed marker
- `pyproject.toml` — MODIFIED: Ensure templates included in wheel, add py.typed

## Task Details

### Step 1: Ensure Template Files Are Included in Wheel

In `pyproject.toml`, the hatch build config already has `packages = ["src/field_check"]`. Jinja2 templates need to be included. Check if hatch automatically includes non-Python files in packages. If not, add:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/field_check"]

[tool.hatch.build.targets.sdist]
include = ["src/field_check"]
```

Hatch includes all files in the package directory by default (including templates/), so this should work. Verify with `uv build` and inspect the wheel.

Also add `py.typed` marker:
```bash
touch src/field_check/py.typed
```

### Step 2: Rewrite README.md

Create a comprehensive showcase README (~200 lines) with:

**Structure:**
1. **Header** — Name, one-line description, badges (PyPI version, Python version, License, CI)
2. **What it does** — 3-4 sentence elevator pitch
3. **Terminal output showcase** — Code block showing actual `field-check scan` terminal output (captured from a real scan, cleaned up for presentation). Use a representative corpus showing multiple sections.
4. **Quick install** — `pip install field-check` + `pipx install field-check`
5. **Usage examples:**
   - Basic scan: `field-check scan ./my-documents/`
   - HTML report: `field-check scan ./corpus/ --format html`
   - JSON for CI: `field-check scan ./data/ --format json`
   - CSV export: `field-check scan ./docs/ --format csv -o inventory.csv`
   - Custom sampling: `field-check scan ./large-corpus/ --sampling-rate 0.05`
   - With excludes: `field-check scan . --exclude "*.log" --exclude "node_modules"`
6. **What it scans** — Feature bullet list:
   - File inventory (types, sizes, directory structure)
   - BLAKE3 exact duplicate detection
   - Corrupt/encrypted/empty file detection
   - PII risk indicators (email, CC, SSN, phone, IP)
   - Language detection (7 languages + Unicode script)
   - Encoding detection
   - Near-duplicate detection (SimHash)
   - Scanned vs native PDF classification
7. **Configuration** — Show `.field-check.yaml` example with key options
8. **CI/CD Integration** — Exit codes explanation (0/1/2)
9. **Output formats** — Brief description of terminal/HTML/JSON/CSV
10. **Privacy** — "All processing is local. No data is transmitted."
11. **License** — Apache 2.0
12. **Links** — PyPI, GitHub, Field website

**Badge URLs** (use shields.io):
```markdown
[![PyPI](https://img.shields.io/pypi/v/field-check)](https://pypi.org/project/field-check/)
[![Python](https://img.shields.io/pypi/pyversions/field-check)](https://pypi.org/project/field-check/)
[![License](https://img.shields.io/github/license/usefield/field-check)](LICENSE)
```

**Terminal output block:**
Run `field-check scan` against a sample corpus and capture the output. Clean it up for presentation (trim paths, use representative file counts). Present as a code block with `console` language tag.

### Step 3: Create py.typed Marker

Create empty `src/field_check/py.typed` file for PEP 561 compliance.

### Step 4: Build and Verify Wheel

```bash
uv build
```

Inspect the wheel to verify:
- Templates are included (`field_check/templates/report.html`)
- py.typed marker is included
- Package structure is correct

### Step 5: Lint Check

```bash
uv run ruff check .
```

## Verification
- [ ] README.md contains all sections (badges, install, usage, features, config, CI, privacy)
- [ ] `py.typed` exists at `src/field_check/py.typed`
- [ ] `uv build` succeeds
- [ ] Wheel contains templates and py.typed
- [ ] `uv run ruff check .` — lint clean

## Done When
- README is a polished showcase ready for PyPI
- Package builds correctly with all assets
- py.typed marker present

## Notes
- Badge URLs will show "not found" until actually published to PyPI — that's expected
- Terminal output in README should be static text, not a screenshot (more accessible, copy-pasteable)
- Keep README under 250 lines — comprehensive but not overwhelming
- Don't include animated GIFs (they're large and slow to load) — use code blocks instead
