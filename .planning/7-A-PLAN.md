# Phase 7 - Plan A: JSON + CSV Export Modules + CI Exit Codes + Config

## Overview
Create JSON and CSV report renderers, add CI exit code logic, and add threshold configuration to FieldCheckConfig. These are pure data serialization modules with no visual design.

## Prerequisites
- All scanner modules exist (Phases 1-6 complete)
- Report dispatcher (`report/__init__.py`) already accepts all result types

## Files to Create/Modify
- `src/field_check/report/json_report.py` — NEW: JSON renderer
- `src/field_check/report/csv_report.py` — NEW: CSV renderer
- `src/field_check/config.py` — MODIFIED: Add threshold config fields
- `src/field_check/report/__init__.py` — MODIFIED: Wire JSON/CSV/exit codes

## Task Details

### Step 1: Add Threshold Config Fields

In `src/field_check/config.py`:

1. Add fields to `FieldCheckConfig` dataclass:
   ```python
   pii_critical: float = 0.05          # >= 5% files with PII → exit 1
   duplicate_critical: float = 0.10    # >= 10% exact duplicates → exit 1
   corrupt_critical: float = 0.01      # >= 1% corrupt files → exit 1
   ```

2. Add YAML parsing for `thresholds` section (after simhash section):
   ```python
   # Parse thresholds config
   pii_critical = 0.05
   duplicate_critical = 0.10
   corrupt_critical = 0.01
   thresholds = raw.get("thresholds", {})
   if isinstance(thresholds, dict):
       pii_t = thresholds.get("pii_critical")
       if isinstance(pii_t, (int, float)):
           pii_critical = max(0.0, min(1.0, float(pii_t)))
       dup_t = thresholds.get("duplicate_critical")
       if isinstance(dup_t, (int, float)):
           duplicate_critical = max(0.0, min(1.0, float(dup_t)))
       cor_t = thresholds.get("corrupt_critical")
       if isinstance(cor_t, (int, float)):
           corrupt_critical = max(0.0, min(1.0, float(cor_t)))
   ```

3. Pass the three new fields to `FieldCheckConfig(...)` constructor.

### Step 2: Create JSON Report Module

Create `src/field_check/report/json_report.py` (~200 lines):

```python
"""JSON report renderer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from field_check import __version__
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.sampling import SampleResult
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import TextExtractionResult
```

**Function: `render_json_report(...) -> str`**

Same signature as `render_terminal_report` (minus `console`, plus returns `str`).

Build a dict with these top-level keys:

```python
{
    "version": __version__,
    "scan_path": str(walk_result.scan_root),
    "scan_date": datetime.now().isoformat(),
    "duration_seconds": elapsed_seconds,
    "summary": {
        "total_files": inventory.total_files,
        "total_size": inventory.total_size,
        "type_distribution": {mime: count for mime, count in inventory.type_counts.items()},
        "size_distribution": {
            "buckets": [{"label": b.label, "count": b.count} for b in inventory.size_distribution.buckets],
            "min": inventory.size_distribution.min_size,
            "max": inventory.size_distribution.max_size,
            "median": inventory.size_distribution.median_size,
            "mean": inventory.size_distribution.mean_size,
        },
        "age_distribution": {...},
        "directory_structure": {...},
        "duplicates": {...} or None,
        "corruption": {...} or None,
        "pii": {...} or None,
        "language": {...} or None,
        "encoding": {...} or None,
        "near_duplicates": {...} or None,
    },
    "files": [
        {
            "path": str(file.relative_path),
            "size": file.size,
            "mime_type": inventory.file_types.get(file.path, "unknown"),
            "blake3": hash or None,
            "is_duplicate": bool,
            "health_status": "ok"|"corrupt"|...,
            "has_pii": bool,
            "pii_types": [...] or None,
            "language": str or None,
            "encoding": str or None,
        }
    ]
}
```

**Key implementation details:**
- Build a lookup dict from `dedup_result` to flag `is_duplicate` per file (check if file's hash appears in any duplicate_group)
- Build lookup from `corruption_result.flagged_files` for health status
- Build lookup from `pii_result.file_results` for PII flags
- Build lookup from `language_result.file_results` for language
- Build lookup from `encoding_result.file_results` for encoding
- For files not in sample: set sampled fields to `null`
- Use `json.dumps(data, indent=2)` for pretty-printing
- All Path objects must be converted to `str()`

### Step 3: Create CSV Report Module

Create `src/field_check/report/csv_report.py` (~100 lines):

```python
"""CSV report renderer."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.simhash import SimHashResult
```

**Function: `render_csv_report(...) -> str`**

Same parameter signature as JSON (minus console).

**Columns:**
```
path, size, mime_type, blake3, is_duplicate, health_status, has_pii, pii_types, language, encoding
```

**Implementation:**
- Use `csv.writer` with `io.StringIO()`
- Write header row
- One row per file from `walk_result.files`
- Same lookup dicts as JSON for per-file flags
- For sampled fields not available: empty string
- `pii_types` as semicolon-separated list (e.g., "email;ssn")
- Return the string content

### Step 4: Wire Into Report Dispatcher + Add Exit Code Logic

In `src/field_check/report/__init__.py`:

1. Add imports:
   ```python
   from field_check.report.json_report import render_json_report
   from field_check.report.csv_report import render_csv_report
   from field_check.config import FieldCheckConfig
   ```

2. Add `config: FieldCheckConfig | None = None` parameter to `generate_report()`.

3. Add format handlers:
   ```python
   elif fmt == "json":
       content = render_json_report(
           inventory, walk_result, elapsed_seconds,
           dedup_result=dedup_result, corruption_result=corruption_result,
           sample_result=sample_result, text_result=text_result,
           pii_result=pii_result, language_result=language_result,
           encoding_result=encoding_result, simhash_result=simhash_result,
       )
       path = output_path or Path("field-check-report.json")
       path.write_text(content, encoding="utf-8")
       console.print(f"Report saved to [bold]{path}[/bold]")
   elif fmt == "csv":
       content = render_csv_report(...)
       path = output_path or Path("field-check-report.csv")
       path.write_text(content, encoding="utf-8")
       console.print(f"Report saved to [bold]{path}[/bold]")
   ```

4. Change the `else` clause to only raise for unsupported formats (remove "html" from error since we'll add it in Plan B).

5. Add `determine_exit_code()` function:
   ```python
   def determine_exit_code(
       config: FieldCheckConfig,
       inventory: InventoryResult,
       dedup_result: DedupResult | None = None,
       corruption_result: CorruptionResult | None = None,
       pii_result: PIIScanResult | None = None,
   ) -> int:
       """Determine CI exit code based on configured thresholds.

       Returns:
           0 if no critical findings, 1 if any threshold exceeded.
       """
       if dedup_result is not None:
           dup_rate = dedup_result.duplicate_percentage / 100.0
           if dup_rate >= config.duplicate_critical:
               return 1
       if corruption_result is not None and inventory.total_files > 0:
           corrupt_rate = corruption_result.corrupt_count / inventory.total_files
           if corrupt_rate >= config.corrupt_critical:
               return 1
       if pii_result is not None and pii_result.total_scanned > 0:
           pii_rate = pii_result.files_with_pii / pii_result.total_scanned
           if pii_rate >= config.pii_critical:
               return 1
       return 0
   ```

### Step 5: Lint Check

Run `uv run ruff check .` — ensure lint clean.

## Verification
- [ ] `uv run python -c "from field_check.report.json_report import render_json_report"` succeeds
- [ ] `uv run python -c "from field_check.report.csv_report import render_csv_report"` succeeds
- [ ] `uv run python -c "from field_check.report import determine_exit_code"` succeeds
- [ ] Config parses `thresholds` section from YAML
- [ ] `uv run ruff check .` — lint clean

## Done When
- JSON renderer outputs valid, pretty-printed JSON with summary + per-file data
- CSV renderer outputs valid CSV with header + one row per file
- Exit code function returns 0/1 based on thresholds
- Config supports `thresholds.pii_critical`, `thresholds.duplicate_critical`, `thresholds.corrupt_critical`
- Lint clean

## Notes
- JSON should NOT include PII matched text (Invariant 3) — only counts and pattern types
- CSV should NOT include PII matched text either
- All Path objects must be converted to str() for serialization
- JSON uses `json.dumps(indent=2)` for readability
- CSV uses standard `csv.writer` — no pandas dependency
- The exit code logic goes in `report/__init__.py` since it's called after report generation
