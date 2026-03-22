# Phase 8 - Plan B: GitHub Actions CI + Publish Workflow

## Overview
Create GitHub Actions workflows for CI (test + lint on PRs) and PyPI publishing (trusted publisher via OIDC on release tags).

## Prerequisites
- Plan A complete (README, package builds correctly)

## Files to Create/Modify
- `.github/workflows/ci.yml` — NEW: Test + lint CI workflow
- `.github/workflows/publish.yml` — NEW: PyPI publish on tag push
- `pyproject.toml` — MODIFIED: Bump version if needed, verify build config

## Task Details

### Step 1: Create CI Workflow

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v4
      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Lint
        run: uv run ruff check .
      - name: Format check
        run: uv run ruff format --check .
      - name: Test
        run: uv run pytest --cov --cov-fail-under=80
```

**Key decisions:**
- Matrix: ubuntu + windows, Python 3.11-3.13
- Uses `astral-sh/setup-uv@v4` for fast UV install
- Lint + format check + tests with coverage
- Triggered on PRs to main only (per discussion)

### Step 2: Create Publish Workflow

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # Required for trusted publishing
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v4
      - name: Set up Python
        run: uv python install 3.12
      - name: Build package
        run: uv build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

**Key decisions:**
- Triggered on version tags (`v0.1.0`, `v1.0.0`, etc.)
- Uses trusted publishing (OIDC) — no API tokens needed
- Requires `pypi` environment configured in GitHub repo settings
- Uses `pypa/gh-action-pypi-publish@release/v1` official action
- Builds with UV, publishes the dist/

### Step 3: Verify CI Workflow Syntax

```bash
# Check YAML syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
python -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml'))"
```

### Step 4: Verify Package Builds

```bash
uv build
ls -la dist/
```

Ensure both `.tar.gz` and `.whl` are produced.

### Step 5: Lint Check

```bash
uv run ruff check .
```

## Verification
- [ ] `.github/workflows/ci.yml` exists with valid YAML
- [ ] `.github/workflows/publish.yml` exists with valid YAML
- [ ] CI triggers on PRs to main only
- [ ] Publish triggers on `v*` tags only
- [ ] `uv build` produces `.tar.gz` and `.whl`
- [ ] `uv run ruff check .` — lint clean

## Done When
- CI workflow tests on ubuntu + windows, Python 3.11-3.13
- Publish workflow uses trusted publishing (OIDC)
- Package builds correctly
- All YAML is valid

## Notes
- Trusted publishing requires the repo owner to configure the `pypi` environment in GitHub repo settings and add the PyPI trusted publisher
- The publish workflow won't work until the GitHub repo exists and PyPI trusted publisher is configured — that's a manual step outside this plan
- CI matrix covers the same Python versions as pyproject.toml classifiers
- Windows testing is important since blake3 and pdfplumber have platform-specific behavior
- The `setup-uv` action caches UV globally for faster CI runs
