# Phase 4 - Plan A: PII Scanner + Page Count Analysis

## Overview
Create the PII regex scanning module with Luhn validation and page count distribution analysis. This is the core logic — no CLI or report integration yet.

## Prerequisites
- Phase 3 complete (sampling framework, text extraction pipeline)
- config.py with FieldCheckConfig dataclass
- scanner/text.py with _extract_pdf, _extract_docx, and ProcessPoolExecutor pattern
- scanner/sampling.py with SampleResult and confidence interval utilities

## Files to Create/Modify
- `src/field_check/scanner/pii.py` — NEW: PII regex patterns, Luhn validation, PII scanner
- `src/field_check/config.py` — Add pii_custom_patterns and show_pii_samples to FieldCheckConfig
- `src/field_check/scanner/text.py` — Add page_count_distribution to TextExtractionResult

## Task Details

### Step 1: Add PII + page config fields to FieldCheckConfig

In `config.py`:

1. Add fields to `FieldCheckConfig`:
   ```python
   pii_custom_patterns: list[dict[str, str]] = field(default_factory=list)
   show_pii_samples: bool = False
   ```

2. In `load_config()`, parse the `pii` section from YAML:
   ```yaml
   pii:
     custom_patterns:
       - name: "UK NI Number"
         pattern: "[A-Z]{2}\\d{6}[A-Z]"
   ```
   - Validate each pattern has `name` (str) and `pattern` (str)
   - Compile regex to validate pattern syntax, log warning if invalid
   - Store as list of dicts: `[{"name": "UK NI Number", "pattern": r"[A-Z]{2}\d{6}[A-Z]"}]`

### Step 2: Create PII scanner module (scanner/pii.py)

Create `src/field_check/scanner/pii.py` with:

**Constants and dataclasses:**

```python
import re

# Built-in PII patterns with expected FP rates
BUILTIN_PATTERNS: list[dict[str, str | float]] = [
    {
        "name": "email",
        "label": "Email Address",
        "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "fp_rate": 0.10,
    },
    {
        "name": "credit_card",
        "label": "Credit Card Number",
        "pattern": r"\b(?:\d[ -]*?){13,19}\b",  # loose match, Luhn validates
        "fp_rate": 0.20,
        "validator": "luhn",
    },
    {
        "name": "ssn",
        "label": "SSN (US)",
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "fp_rate": 0.40,
    },
    {
        "name": "phone",
        "label": "Phone Number",
        "pattern": r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b",
        "fp_rate": 0.50,
    },
    {
        "name": "ip_address",
        "label": "IP Address",
        "pattern": r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
        "fp_rate": 0.15,
    },
]

@dataclass
class PIIMatch:
    """A single PII match in a file."""
    pattern_name: str
    matched_text: str  # Only stored when show_pii_samples=True
    line_number: int

@dataclass
class PIIFileResult:
    """PII scan result for a single file."""
    path: str
    matches_by_type: dict[str, int] = field(default_factory=dict)
    sample_matches: list[PIIMatch] = field(default_factory=list)  # Only populated with --show-pii-samples
    error: str | None = None

@dataclass
class PIIScanResult:
    """Aggregate PII scan results."""
    total_scanned: int = 0
    files_with_pii: int = 0
    per_type_counts: dict[str, int] = field(default_factory=dict)  # pattern_name -> total matches
    per_type_file_counts: dict[str, int] = field(default_factory=dict)  # pattern_name -> files with matches
    pattern_labels: dict[str, str] = field(default_factory=dict)  # pattern_name -> display label
    pattern_fp_rates: dict[str, float] = field(default_factory=dict)  # pattern_name -> expected FP rate
    file_results: list[PIIFileResult] = field(default_factory=list)
    scan_errors: int = 0
    show_pii_samples: bool = False
```

**Luhn validator:**

```python
def _luhn_check(number_str: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    # Standard Luhn: double every second digit from right
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0
```

**Text extraction for PII (expanded hybrid):**

```python
# MIME types that PII scanner can extract text from
PII_EXTRACTABLE_MIMES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/csv",
    "text/json",
    "text/xml",
    "application/json",
    "application/xml",
}

def _extract_text_for_pii(filepath: str, mime_type: str) -> str:
    """Extract text content from a file for PII scanning.

    For PDF/DOCX: uses pdfplumber/python-docx (same as text.py).
    For plain text types: reads raw bytes with charset-normalizer.
    """
    if mime_type == "application/pdf":
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            return "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        # Plain text types — read bytes, detect encoding
        from charset_normalizer import from_bytes
        raw = open(filepath, "rb").read(1_000_000)  # Cap at 1MB
        result = from_bytes(raw).best()
        return str(result) if result else raw.decode("utf-8", errors="replace")
```

**Single-file PII scanner (ProcessPoolExecutor worker):**

```python
def _scan_single_file(
    filepath: str,
    mime_type: str,
    compiled_patterns: list[tuple[str, str, re.Pattern, str | None]],
    show_samples: bool,
) -> PIIFileResult:
    """Scan a single file for PII patterns. Top-level for pickling."""
    result = PIIFileResult(path=filepath)
    try:
        text = _extract_text_for_pii(filepath, mime_type)
        if not text:
            return result

        lines = text.split("\n")
        for line_num, line in enumerate(lines, 1):
            for name, label, pattern, validator in compiled_patterns:
                for match in pattern.finditer(line):
                    matched = match.group()
                    # Apply validator if specified
                    if validator == "luhn" and not _luhn_check(matched):
                        continue
                    result.matches_by_type[name] = result.matches_by_type.get(name, 0) + 1
                    if show_samples and len(result.sample_matches) < 5:
                        result.sample_matches.append(
                            PIIMatch(pattern_name=name, matched_text=matched, line_number=line_num)
                        )
    except Exception as exc:
        result.error = str(exc)
    return result
```

**Aggregate scanner:**

```python
def scan_pii(
    sample: SampleResult,
    inventory: InventoryResult,
    config: FieldCheckConfig,
    max_workers: int | None = None,
    timeout: float = 30.0,
    progress_callback: Callable[[int, int], None] | None = None,
) -> PIIScanResult:
    """Scan sampled files for PII patterns using ProcessPoolExecutor."""
    result = PIIScanResult(show_pii_samples=config.show_pii_samples)

    # Build pattern list: built-in + custom
    patterns: list[tuple[str, str, re.Pattern, str | None]] = []
    for p in BUILTIN_PATTERNS:
        compiled = re.compile(p["pattern"])
        patterns.append((p["name"], p["label"], compiled, p.get("validator")))
        result.pattern_labels[p["name"]] = p["label"]
        result.pattern_fp_rates[p["name"]] = p.get("fp_rate", 0.0)

    for custom in config.pii_custom_patterns:
        name = custom["name"]
        compiled = re.compile(custom["pattern"])
        patterns.append((name, name, compiled, None))
        result.pattern_labels[name] = name
        result.pattern_fp_rates[name] = 0.0  # Unknown FP rate

    # Filter to PII-extractable files from sample
    extractable = []
    for entry in sample.selected_files:
        mime = inventory.file_types.get(entry.path, "application/octet-stream")
        if mime in PII_EXTRACTABLE_MIMES:
            extractable.append((entry, mime))

    if not extractable:
        return result

    total = len(extractable)
    workers = max_workers or min(4, os.cpu_count() or 1)

    # NOTE: compiled regex patterns can't be pickled across processes.
    # Pass pattern specs as serializable tuples, compile inside worker.
    pattern_specs = [
        (name, label, pat.pattern, validator)
        for name, label, pat, validator in patterns
    ]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_entry = {}
        for entry, mime in extractable:
            future = pool.submit(
                _scan_single_file_from_specs,
                str(entry.path), mime, pattern_specs, config.show_pii_samples,
            )
            future_to_entry[future] = entry

        for completed, future in enumerate(as_completed(future_to_entry), 1):
            try:
                file_result = future.result(timeout=timeout)
            except TimeoutError:
                file_result = PIIFileResult(
                    path=str(future_to_entry[future].path),
                    error="PII scan timed out",
                )
                result.scan_errors += 1
            except Exception as exc:
                file_result = PIIFileResult(
                    path=str(future_to_entry[future].path),
                    error=str(exc),
                )
                result.scan_errors += 1

            result.file_results.append(file_result)
            result.total_scanned += 1

            if file_result.error:
                result.scan_errors += 1
            elif file_result.matches_by_type:
                result.files_with_pii += 1
                for pname, count in file_result.matches_by_type.items():
                    result.per_type_counts[pname] = result.per_type_counts.get(pname, 0) + count
                    result.per_type_file_counts[pname] = result.per_type_file_counts.get(pname, 0) + 1

            if progress_callback:
                progress_callback(completed, total)

    return result
```

**Important:** Because `re.Pattern` objects can't be pickled, the actual worker must accept serializable pattern specs and compile them inside the worker process:

```python
def _scan_single_file_from_specs(
    filepath: str,
    mime_type: str,
    pattern_specs: list[tuple[str, str, str, str | None]],
    show_samples: bool,
) -> PIIFileResult:
    """Worker entry point. Compiles patterns from specs, then scans."""
    compiled = [
        (name, label, re.compile(pat_str), validator)
        for name, label, pat_str, validator in pattern_specs
    ]
    return _scan_single_file(filepath, mime_type, compiled, show_samples)
```

### Step 3: Add page count distribution to TextExtractionResult

In `scanner/text.py`:

1. Add page count tracking fields to `TextExtractionResult`:
   ```python
   page_count_total: int = 0
   page_count_min: int = 0
   page_count_max: int = 0
   page_count_distribution: dict[str, int] = field(default_factory=dict)
   # Buckets: "1", "2-5", "6-10", "11-50", "51-100", "101-500", ">500"
   ```

2. In `extract_text()`, after processing each non-error result with page_count > 0:
   ```python
   if text_result.page_count > 0:
       result.page_count_total += text_result.page_count
       if result.page_count_min == 0 or text_result.page_count < result.page_count_min:
           result.page_count_min = text_result.page_count
       if text_result.page_count > result.page_count_max:
           result.page_count_max = text_result.page_count
       # Bucket
       bucket = _page_count_bucket(text_result.page_count)
       result.page_count_distribution[bucket] = result.page_count_distribution.get(bucket, 0) + 1
   ```

3. Add helper function:
   ```python
   PAGE_COUNT_BUCKETS = [
       (1, 1, "1 page"),
       (2, 5, "2-5 pages"),
       (6, 10, "6-10 pages"),
       (11, 50, "11-50 pages"),
       (51, 100, "51-100 pages"),
       (101, 500, "101-500 pages"),
       (501, float("inf"), ">500 pages"),
   ]

   def _page_count_bucket(count: int) -> str:
       for low, high, label in PAGE_COUNT_BUCKETS:
           if low <= count <= high:
               return label
       return ">500 pages"
   ```

### Step 4: Lint and verify

- Run `uv run ruff check src/field_check/scanner/pii.py src/field_check/config.py src/field_check/scanner/text.py`
- Run `uv run pytest tests/test_text.py tests/test_sampling.py -q` to confirm no regressions

## Verification
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest tests/ -q` — existing tests still pass
- [ ] `python -c "from field_check.scanner.pii import scan_pii, PIIScanResult"` imports cleanly
- [ ] `python -c "from field_check.config import FieldCheckConfig; c = FieldCheckConfig(); print(c.pii_custom_patterns)"` prints `[]`

## Done When
- pii.py module exists with 5 built-in patterns, Luhn validation, expanded hybrid text extraction, ProcessPoolExecutor scanner
- config.py supports pii_custom_patterns and show_pii_samples
- text.py tracks page count distribution in TextExtractionResult
- All existing tests pass

## Notes
- `re.Pattern` can't be pickled — must serialize as pattern strings and compile inside worker
- Credit card pattern is loose (13-19 digits with separators); Luhn does the real validation
- Phone pattern has highest FP rate (0.50) — documented in pattern metadata
- charset-normalizer used for plain text encoding detection (already a dependency)
- Cap plain text file reads at 1MB to avoid memory issues
- PII match content is NEVER stored unless show_pii_samples=True (Invariant 3)
