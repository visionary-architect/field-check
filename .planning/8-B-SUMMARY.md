# Phase 8 - Plan B Summary: GitHub Actions CI + Publish Workflow

## Status: Complete

## What Was Done
- Created `.github/workflows/ci.yml` — test + lint CI on PRs to main
- Created `.github/workflows/publish.yml` — PyPI trusted publishing on v* tags
- Verified both YAML files parse correctly
- Lint check passes on project source

## Files Changed
- `.github/workflows/ci.yml` — NEW: CI workflow (ubuntu + windows, Python 3.11-3.13)
- `.github/workflows/publish.yml` — NEW: PyPI publish via OIDC trusted publisher

## Verification Results
- [x] ci.yml valid YAML
- [x] publish.yml valid YAML
- [x] CI triggers on PRs to main only
- [x] Publish triggers on v* tags only
- [x] CI matrix: ubuntu-latest + windows-latest, Python 3.11/3.12/3.13
- [x] Publish uses trusted publishing (id-token: write permission)
- [x] Lint scoped to src/ tests/ (avoids hooks false positives)

## Commit
- Hash: a28a52b
- Message: chore(8-B): add GitHub Actions CI and PyPI publish workflows

## Notes
- Trusted publishing requires configuring `pypi` environment in GitHub repo settings
- PyPI trusted publisher must be added manually after repo is created on GitHub
- CI lint/format scoped to `src/ tests/` to match project source
