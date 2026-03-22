"""JUnit XML report renderer for CI/CD integration.

Generates JUnit XML where each file is a test case and findings are failures.
No external dependencies — uses stdlib xml.etree.ElementTree.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.pii import PIIScanResult


def render_junit_report(
    inventory: InventoryResult,
    walk_result: WalkResult,
    elapsed_seconds: float = 0.0,
    corruption_result: CorruptionResult | None = None,
    pii_result: PIIScanResult | None = None,
    dedup_result: DedupResult | None = None,
    **_kwargs: object,
) -> str:
    """Render findings as JUnit XML.

    Each scanned file becomes a test case. Files with findings get
    failure elements. Clean files are passing test cases.

    Args:
        inventory: Inventory results.
        walk_result: Walk results with file list.
        elapsed_seconds: Total scan duration.
        corruption_result: Corruption findings (optional).
        pii_result: PII findings (optional).
        dedup_result: Duplicate findings (optional).

    Returns:
        JUnit XML string.
    """
    # Build lookup dicts for findings
    corruption_lookup = _build_corruption_lookup(corruption_result)
    pii_lookup = _build_pii_lookup(pii_result)
    dup_paths = _build_dup_paths(dedup_result)

    # Create test suite
    testsuite = Element("testsuite")
    testsuite.set("name", "field-check")
    testsuite.set("tests", str(inventory.total_files))
    testsuite.set("time", f"{elapsed_seconds:.3f}")

    failures = 0
    errors = 0

    for entry in walk_result.files:
        path_str = str(entry.path)
        rel_path = _try_relative(entry.path, walk_result.scan_root)

        testcase = SubElement(testsuite, "testcase")
        testcase.set("name", rel_path)
        testcase.set("classname", "field-check.scan")

        # Check for findings
        findings: list[tuple[str, str]] = []

        # Corruption
        status_detail = corruption_lookup.get(path_str)
        if status_detail is not None:
            status, detail = status_detail
            if status in ("corrupt", "truncated"):
                findings.append(("error", f"[{status}] {detail}"))
            else:
                findings.append(("failure", f"[{status}] {detail}"))

        # PII (counts only — Invariant 3)
        pii_types = pii_lookup.get(path_str)
        if pii_types:
            type_list = ", ".join(pii_types)
            findings.append(
                (
                    "failure",
                    f"PII risk indicators found: {type_list}",
                )
            )

        # Duplicates
        if path_str in dup_paths:
            findings.append(("failure", "File is an exact duplicate"))

        # Add findings as failure/error elements
        for kind, message in findings:
            if kind == "error":
                errors += 1
                elem = SubElement(testcase, "error")
            else:
                failures += 1
                elem = SubElement(testcase, "failure")
            elem.set("message", message)
            elem.set("type", "finding")

    testsuite.set("failures", str(failures))
    testsuite.set("errors", str(errors))

    xml_bytes = tostring(testsuite, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'


def _build_corruption_lookup(
    corruption: CorruptionResult | None,
) -> dict[str, tuple[str, str]]:
    """Build path → (status, detail) lookup."""
    lookup: dict[str, tuple[str, str]] = {}
    if corruption is None:
        return lookup
    for fh in corruption.flagged_files:
        lookup[str(fh.path)] = (fh.status, fh.detail)
    return lookup


def _build_pii_lookup(
    pii: PIIScanResult | None,
) -> dict[str, list[str]]:
    """Build path → list of PII pattern types."""
    lookup: dict[str, list[str]] = {}
    if pii is None:
        return lookup
    for fr in pii.file_results:
        if fr.matches_by_type:
            lookup[fr.path] = list(fr.matches_by_type.keys())
    return lookup


def _build_dup_paths(dedup: DedupResult | None) -> set[str]:
    """Build set of all duplicate file paths."""
    paths: set[str] = set()
    if dedup is None:
        return paths
    for group in dedup.duplicate_groups:
        for p in group.paths:
            paths.add(str(p))
    return paths


def _try_relative(path: Path, root: Path) -> str:
    """Return path relative to root if possible."""
    try:
        return str(path.relative_to(root))
    except (ValueError, TypeError):
        return str(path)
