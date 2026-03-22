# Phase 7 - Plan B: HTML Report with Chart.js

## Overview
Create a self-contained HTML report using Jinja2 template with embedded Chart.js for interactive charts. The HTML file must have zero external dependencies.

## Prerequisites
- Plan A complete (JSON/CSV modules exist, report dispatcher updated)
- jinja2 already in pyproject.toml dependencies

## Files to Create/Modify
- `src/field_check/templates/report.html` — NEW: Jinja2 HTML template with inline CSS + Chart.js
- `src/field_check/report/html.py` — NEW: HTML renderer using Jinja2
- `src/field_check/report/__init__.py` — MODIFIED: Wire HTML format handler

## Task Details

### Step 1: Create HTML Renderer Module

Create `src/field_check/report/html.py` (~120 lines):

```python
"""HTML report renderer using Jinja2."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import jinja2

from field_check import __version__
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult
from field_check.scanner.sampling import SampleResult, compute_confidence_interval, format_ci
from field_check.scanner.simhash import SimHashResult
from field_check.scanner.text import TextExtractionResult
```

**Function: `render_html_report(...) -> str`**

Same parameter signature as terminal report (minus `console`).

**Implementation:**
1. Load Jinja2 template from `templates/report.html` using `PackageLoader`:
   ```python
   env = jinja2.Environment(
       loader=jinja2.PackageLoader("field_check", "templates"),
       autoescape=jinja2.select_autoescape(["html"]),
   )
   template = env.get_template("report.html")
   ```

2. Build a context dict with all the data the template needs. Process the data in Python (not in Jinja2) for simplicity:

   ```python
   context = {
       "version": __version__,
       "scan_path": str(walk_result.scan_root),
       "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
       "duration": _format_duration(elapsed_seconds),
       "total_files": inventory.total_files,
       "total_size": _format_size(inventory.total_size),
       "total_dirs": inventory.dir_structure.total_dirs,
       # Type distribution for chart + table
       "type_labels": [...],  # list of mime types
       "type_counts": [...],  # list of counts
       "type_rows": [...],    # list of dicts for table
       # Size distribution for chart
       "size_labels": [...],
       "size_counts": [...],
       "size_stats": {...},
       # Dedup data
       "dedup": {...} or None,
       # Corruption data
       "corruption": {...} or None,
       # PII data
       "pii": {...} or None,
       # Language data (for chart + table)
       "language": {...} or None,
       # Encoding data
       "encoding": {...} or None,
       # Near-duplicate data
       "simhash": {...} or None,
       # Age distribution
       "age": {...},
       # Directory structure
       "dir_structure": {...},
   }
   ```

3. Helper functions `_format_size()` and `_format_duration()` — copy from terminal.py or import a shared version.

4. Return `template.render(**context)`.

### Step 2: Create Jinja2 HTML Template

Create `src/field_check/templates/report.html`:

This is a self-contained HTML file. Structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Field Check Report — {{ scan_path }}</title>
    <script>/* Chart.js v4.x minified inline */</script>
    <style>
        /* Inline CSS — dark theme to match terminal aesthetic */
        :root {
            --bg: #1a1a2e;
            --surface: #16213e;
            --text: #e0e0e0;
            --accent: #0f3460;
            --highlight: #e94560;
            --success: #4ecca3;
            --warning: #f0a500;
        }
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: var(--surface); border-radius: 8px; padding: 24px; margin-bottom: 24px; border-left: 4px solid var(--highlight); }
        .section { background: var(--surface); border-radius: 8px; padding: 20px; margin-bottom: 16px; }
        .section h2 { margin-top: 0; color: var(--highlight); font-size: 1.1rem; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1); }
        th { color: var(--success); font-weight: 600; }
        .chart-container { max-width: 500px; margin: 16px auto; }
        .stat { display: inline-block; margin-right: 24px; }
        .stat-value { font-size: 1.5rem; font-weight: bold; color: var(--success); }
        .stat-label { font-size: 0.85rem; color: rgba(255,255,255,0.6); }
        .footer { text-align: center; color: rgba(255,255,255,0.4); font-size: 0.85rem; padding: 24px; }
        @media print { body { background: white; color: black; } .section { border: 1px solid #ddd; } }
    </style>
</head>
<body>
<div class="container">
    <!-- Header -->
    <div class="header">
        <h1>Field Check — Document Corpus Health Report</h1>
        <div class="stat"><span class="stat-label">Scan path</span><br><span>{{ scan_path }}</span></div>
        <div class="stat"><span class="stat-label">Date</span><br><span>{{ scan_date }}</span></div>
        <div class="stat"><span class="stat-label">Duration</span><br><span>{{ duration }}</span></div>
        <div class="stat"><span class="stat-value">{{ total_files }}</span><br><span class="stat-label">Files</span></div>
        <div class="stat"><span class="stat-value">{{ total_size }}</span><br><span class="stat-label">Total Size</span></div>
    </div>

    <!-- Section: File Types (pie chart + table) -->
    {% if type_rows %}
    <div class="section">
        <h2>File Type Distribution</h2>
        <div class="chart-container"><canvas id="typeChart"></canvas></div>
        <table>...</table>
    </div>
    {% endif %}

    <!-- Section: Duplicates -->
    {% if dedup %}
    <div class="section">
        <h2>Duplicate Detection</h2>
        <table>...</table>
    </div>
    {% endif %}

    <!-- Section: File Health -->
    {% if corruption %}...{% endif %}

    <!-- Section: PII Risk Indicators -->
    {% if pii %}...{% endif %}

    <!-- Section: Language & Encoding -->
    {% if language or encoding %}...{% endif %}

    <!-- Section: Near-Duplicates -->
    {% if simhash %}...{% endif %}

    <!-- Section: Size Distribution (bar chart) -->
    <div class="section">
        <h2>Size Distribution</h2>
        <div class="chart-container"><canvas id="sizeChart"></canvas></div>
    </div>

    <!-- Section: Age Distribution -->
    ...

    <!-- Section: Directory Structure -->
    ...

    <!-- Footer -->
    <div class="footer">Field Check v{{ version }} — All processing local. No data transmitted.</div>
</div>

<script>
// Chart.js initialization
{% if type_labels %}
new Chart(document.getElementById('typeChart'), {
    type: 'doughnut',
    data: {
        labels: {{ type_labels | tojson }},
        datasets: [{
            data: {{ type_counts | tojson }},
            backgroundColor: ['#e94560','#4ecca3','#0f3460','#f0a500','#533483','#2b6cb0','#e07c24','#38a169'],
        }]
    },
    options: { responsive: true, plugins: { legend: { position: 'right', labels: { color: '#e0e0e0' } } } }
});
{% endif %}

{% if size_labels %}
new Chart(document.getElementById('sizeChart'), {
    type: 'bar',
    data: {
        labels: {{ size_labels | tojson }},
        datasets: [{
            label: 'Files',
            data: {{ size_counts | tojson }},
            backgroundColor: '#4ecca3',
        }]
    },
    options: { responsive: true, scales: { y: { ticks: { color: '#e0e0e0' } }, x: { ticks: { color: '#e0e0e0' } } }, plugins: { legend: { display: false } } }
});
{% endif %}
</script>
</body>
</html>
```

**Chart.js inclusion:**
- Download Chart.js v4.x minified (~200KB) and embed inline in `<script>` tag
- OR use a CDN fallback approach: try CDN, fallback to inline
- Decision: **Inline only** (self-contained, no network). Download the minified JS and paste into template.
- To keep template manageable, use `chart.umd.min.js` (~200KB minified)

**To get Chart.js:**
```bash
curl -o /tmp/chart.min.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js
```
Then paste contents into template's `<script>` block.

**Template sections should mirror terminal report:**
1. Header (scan info)
2. File Type Distribution (doughnut chart + table)
3. Duplicate Detection (table)
4. File Health (table)
5. Document Content Analysis (table — scanned detection, classification, metadata)
6. PII Risk Indicators (table — NO matched content, Invariant 3)
7. Language & Encoding (pie chart for language + table)
8. Near-Duplicate Detection (table)
9. Size Distribution (bar chart + stats)
10. File Age Distribution (table)
11. Directory Structure (table)
12. Footer

### Step 3: Wire HTML Into Report Dispatcher

In `src/field_check/report/__init__.py`, add:

1. Import: `from field_check.report.html import render_html_report`

2. Add `elif fmt == "html"` handler:
   ```python
   elif fmt == "html":
       content = render_html_report(
           inventory, walk_result, elapsed_seconds,
           dedup_result=dedup_result, corruption_result=corruption_result,
           sample_result=sample_result, text_result=text_result,
           pii_result=pii_result, language_result=language_result,
           encoding_result=encoding_result, simhash_result=simhash_result,
       )
       path = output_path or Path("field-check-report.html")
       path.write_text(content, encoding="utf-8")
       console.print(f"Report saved to [bold]{path}[/bold]")
   ```

3. Update the `else` clause error message to `"Available: terminal, html, json, csv"`.

### Step 4: Lint Check

Run `uv run ruff check .` — ensure lint clean.

## Verification
- [ ] `uv run field-check scan <test-corpus> --format html` generates `field-check-report.html`
- [ ] HTML file opens in browser and displays all sections
- [ ] Charts render (doughnut for types, bar for sizes)
- [ ] HTML is fully self-contained (disconnect internet, still works)
- [ ] PII section shows counts only, no matched content (Invariant 3)
- [ ] `uv run ruff check .` — lint clean

## Done When
- HTML report generates with all sections matching terminal report
- Chart.js charts render for type distribution and size distribution
- File is self-contained (~215KB with Chart.js inline)
- Dark theme matches terminal aesthetic
- Print styles work for light background

## Notes
- Chart.js UMD build is ~200KB minified — acceptable for a diagnostic report
- Template uses Jinja2 `autoescape` for XSS safety
- `PackageLoader` finds templates via Python package structure
- PII section must NEVER include matched content (Invariant 3)
- All data is pre-processed in Python, template just renders
- Dark theme with `@media print` override for paper printing
- Consider: language distribution could also get a pie chart if >1 language
