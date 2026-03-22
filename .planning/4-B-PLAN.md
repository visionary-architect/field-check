# Phase 4 - Plan B: CLI + Report Integration + Tests

## Overview
Wire PII scanning and page count distribution into the CLI pipeline and terminal report, add `--show-pii-samples` flag, and create comprehensive tests.

## Prerequisites
- Plan A complete (pii.py, config.py updates, text.py page count fields)
- Existing CLI pipeline pattern (cli.py with progress spinners)
- Existing terminal report pattern (terminal.py with sections)

## Files to Create/Modify
- `src/field_check/cli.py` — Add --show-pii-samples flag, PII scan step
- `src/field_check/report/__init__.py` — Add pii_result parameter
- `src/field_check/report/terminal.py` — Add PII Risk Indicators section, page count sub-section
- `tests/test_pii.py` — NEW: PII scanner tests
- `tests/conftest.py` — Add PII test fixtures

## Task Details

### Step 1: Add --show-pii-samples to CLI and wire PII scan

In `cli.py`:

1. Add CLI option:
   ```python
   @click.option(
       "--show-pii-samples", is_flag=True, default=False,
       help="Show matched PII content in report (WARNING: exposes sensitive data).",
   )
   ```

2. Add `show_pii_samples: bool` parameter to `scan()` function.

3. After text extraction, add PII scan step:
   ```python
   # Set show_pii_samples on config
   if show_pii_samples:
       config.show_pii_samples = True

   # Scan for PII patterns
   pii_result = None
   if sample.total_sample_size > 0:
       with console.status(
           "[bold blue]Scanning for PII...", spinner="dots"
       ) as status:
           def on_pii(current: int, total: int) -> None:
               status.update(
                   f"[bold blue]Scanning for PII... "
                   f"[cyan]{current}[/cyan]/[cyan]{total}[/cyan]"
               )
           pii_result = scan_pii(
               sample, inventory, config, progress_callback=on_pii
           )
   ```

4. Pass `pii_result=pii_result` to `generate_report()`.

5. Add import: `from field_check.scanner.pii import scan_pii`

### Step 2: Update report dispatcher

In `report/__init__.py`:

1. Add import: `from field_check.scanner.pii import PIIScanResult`
2. Add parameter: `pii_result: PIIScanResult | None = None`
3. Pass through to `render_terminal_report()`

### Step 3: Add PII + page count sections to terminal report

In `report/terminal.py`:

1. Add import: `from field_check.scanner.pii import PIIScanResult`

2. **Add page count sub-section inside `_render_text_analysis()`:**
   After the metadata completeness section call, add:
   ```python
   _render_page_count_distribution(text, sample, console)
   ```

   New function:
   ```python
   def _render_page_count_distribution(
       text: TextExtractionResult,
       sample: SampleResult,
       console: Console,
   ) -> None:
       """Render page count distribution for documents with pages."""
       if not text.page_count_distribution:
           return

       table = Table(title="Page Count Distribution", show_lines=False)
       table.add_column("Range", style="cyan")
       table.add_column("Count", justify="right")
       table.add_column("%", justify="right")

       total_docs_with_pages = sum(text.page_count_distribution.values())
       # Use the ordered bucket labels from text.py
       from field_check.scanner.text import PAGE_COUNT_BUCKETS
       for _, _, label in PAGE_COUNT_BUCKETS:
           count = text.page_count_distribution.get(label, 0)
           if count > 0 or label in ("1 page", "2-5 pages"):  # Always show first 2 buckets
               pct = count / total_docs_with_pages * 100 if total_docs_with_pages else 0
               table.add_row(label, f"{count:,}", f"{pct:.1f}%")

       console.print(table)
       if total_docs_with_pages > 0:
           console.print(Text(
               f"  Min: {text.page_count_min}  Max: {text.page_count_max}  "
               f"Mean: {text.page_count_total / total_docs_with_pages:.1f}",
               style="dim",
           ))
   ```

3. **Add PII Risk Indicators section (new top-level section):**
   In `render_terminal_report()`, after the text analysis section:
   ```python
   # Section 5: PII Risk Indicators
   if pii_result is not None:
       _render_pii_results(pii_result, sample, console)
   ```

   Add `pii_result: PIIScanResult | None = None` parameter.

   New function:
   ```python
   def _render_pii_results(
       pii: PIIScanResult,
       sample: SampleResult,
       console: Console,
   ) -> None:
       """Render PII risk indicators with per-type breakdown."""
       if pii.total_scanned == 0:
           return

       # Warning banner if samples are shown
       if pii.show_pii_samples:
           console.print(Panel(
               "[bold yellow]WARNING:[/bold yellow] PII samples shown below. "
               "Do not share this report without redacting sensitive data.",
               border_style="yellow",
               title="Privacy Warning",
           ))

       # Summary table
       summary = Table(title="PII Risk Indicators", show_lines=False)
       summary.add_column("Metric", style="cyan")
       summary.add_column("Value", justify="right")
       summary.add_row("Files scanned for PII", f"{pii.total_scanned:,}")
       summary.add_row("Files with PII indicators", f"{pii.files_with_pii:,}")
       if pii.scan_errors:
           summary.add_row("[yellow]Scan errors[/yellow]", f"{pii.scan_errors:,}")
       console.print(summary)

       # Per-type breakdown tables
       if not pii.per_type_counts:
           console.print(Text("  No PII risk indicators found.", style="dim"))
           console.print()
           return

       for pattern_name in pii.per_type_counts:
           label = pii.pattern_labels.get(pattern_name, pattern_name)
           match_count = pii.per_type_counts[pattern_name]
           file_count = pii.per_type_file_counts.get(pattern_name, 0)
           fp_rate = pii.pattern_fp_rates.get(pattern_name, 0.0)

           ci = compute_confidence_interval(
               file_count, pii.total_scanned, sample.total_population_size
           )

           table = Table(title=f"  {label}", show_lines=False)
           table.add_column("Metric", style="cyan")
           table.add_column("Value", justify="right")
           table.add_row("Total matches", f"{match_count:,}")
           table.add_row("Files affected", f"{file_count:,}")
           table.add_row("Corpus exposure", format_ci(ci))
           if fp_rate > 0:
               table.add_row("Expected FP rate", f"~{fp_rate:.0%}")
           console.print(table)

       # Show sample matches if --show-pii-samples
       if pii.show_pii_samples:
           _render_pii_samples(pii, console)

       console.print()
   ```

   Sample rendering function:
   ```python
   def _render_pii_samples(pii: PIIScanResult, console: Console) -> None:
       """Render PII sample matches (only with --show-pii-samples)."""
       samples = []
       for fr in pii.file_results:
           for m in fr.sample_matches:
               samples.append((fr.path, m.pattern_name, m.matched_text, m.line_number))

       if not samples:
           return

       table = Table(title="PII Samples (first 5 per file)", show_lines=False)
       table.add_column("File", style="dim")
       table.add_column("Type")
       table.add_column("Match", style="red")
       table.add_column("Line", justify="right")

       for path, ptype, match, line in samples[:20]:
           # Show only filename, not full path
           short_path = Path(path).name
           label = pii.pattern_labels.get(ptype, ptype)
           table.add_row(short_path, label, match, str(line))

       console.print(table)
       if len(samples) > 20:
           console.print(Text(f"  ... and {len(samples) - 20} more matches", style="dim"))
   ```

4. **Update `_render_issues()` to include PII scan errors:**
   Add `pii_result` parameter, check `pii_result.scan_errors`.

### Step 4: Create test fixtures in conftest.py

Add to `conftest.py`:

```python
def create_pdf_with_pii(path: Path) -> None:
    """Create a PDF containing PII-like content for testing."""
    text = (
        "Contact: john.doe@example.com\n"
        "SSN: 123-45-6789\n"
        "Phone: (555) 123-4567\n"
        "CC: 4111 1111 1111 1111\n"  # Valid Luhn
        "IP: 192.168.1.100\n"
        "Normal text without PII here."
    )
    create_pdf_with_text(path, text)


@pytest.fixture()
def tmp_corpus_with_pii(tmp_path: Path) -> Path:
    """Corpus with files containing PII-like content."""
    # PDF with PII
    create_pdf_with_pii(tmp_path / "pii_doc.pdf")
    # Clean PDF (no PII)
    create_pdf_with_text(tmp_path / "clean.pdf", "No sensitive data here at all.")
    # Text file with PII
    pii_txt = tmp_path / "contacts.txt"
    pii_txt.write_text(
        "Email: alice@test.org\nPhone: 555-987-6543\n",
        encoding="utf-8",
    )
    # CSV with PII-like content
    pii_csv = tmp_path / "data.csv"
    pii_csv.write_text(
        "name,email,ssn\nBob,bob@corp.io,987-65-4321\n",
        encoding="utf-8",
    )
    # Clean text file
    (tmp_path / "readme.txt").write_text("No PII here.", encoding="utf-8")
    return tmp_path
```

### Step 5: Create PII tests (tests/test_pii.py)

Create `tests/test_pii.py` with:

1. **Luhn validation tests:**
   - `test_luhn_valid_cards` — known valid CC numbers return True
   - `test_luhn_invalid_numbers` — random digit strings return False

2. **Pattern matching tests:**
   - `test_email_pattern_matches` — standard emails detected
   - `test_ssn_pattern_matches` — XXX-XX-XXXX format detected
   - `test_phone_pattern_matches` — various phone formats detected
   - `test_ip_address_pattern_matches` — valid IPs detected
   - `test_cc_with_luhn_validation` — only Luhn-valid numbers counted

3. **Scanner integration tests:**
   - `test_scan_pii_detects_email_in_pdf` — scan PDF with email, verify per_type_counts
   - `test_scan_pii_detects_text_file_pii` — scan .txt file, verify PII detected
   - `test_scan_pii_clean_file_no_pii` — clean file has zero matches
   - `test_scan_pii_aggregate_counts` — verify total_scanned, files_with_pii match
   - `test_scan_pii_show_samples_flag` — with show_pii_samples=True, sample_matches populated
   - `test_scan_pii_without_samples_flag` — without flag, sample_matches empty

4. **Custom pattern tests:**
   - `test_custom_pattern_from_config` — custom regex pattern detected in files

5. **Page count distribution tests:**
   - `test_page_count_distribution` — multi-page PDF shows correct bucket
   - `test_page_count_min_max` — verify min/max tracking

### Step 6: Lint and full test run

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest --cov --cov-fail-under=80 -q`

## Verification
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest --cov --cov-fail-under=80 -q` — all tests pass, coverage >= 80%
- [ ] `uv run field-check scan <test-corpus> --sampling-rate 1.0` shows PII Risk Indicators section
- [ ] `uv run field-check scan <test-corpus> --show-pii-samples` shows warning banner + sample matches
- [ ] Page count distribution appears inside Document Content Analysis section

## Done When
- `--show-pii-samples` flag working with yellow warning banner
- PII Risk Indicators section in terminal report with per-type breakdown and CIs
- Page count distribution sub-section inside Document Content Analysis
- All tests pass (new + existing), coverage >= 80%
- PII match content NEVER stored unless --show-pii-samples (Invariant 3)

## Notes
- Invariant 3: PII content never in output unless --show-pii-samples. Must verify sample_matches is empty without the flag.
- Invariant 4: All PII metrics must show confidence intervals since they're sampled.
- Invariant 5: ProcessPoolExecutor for crash isolation in PII scanner.
- The PII section title is "PII Risk Indicators" not "PII Detection" per spec (30-50% FP rate on SSN).
- Per-type breakdown shows expected FP rate to calibrate user expectations.
- Page count distribution goes inside _render_text_analysis(), not as a separate top-level section.
