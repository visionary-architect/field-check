"""JUnit XML report renderer for CI/CD integration.

Generates JUnit XML where each file is a test case and findings are failures.
No external dependencies — uses stdlib xml.etree.ElementTree.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

from field_check.report.utils import (
    build_corruption_detail_lookup,
    build_duplicate_paths,
    build_pii_lookup,
    try_relative,
)
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
    corruption_lookup = build_corruption_detail_lookup(corruption_result)
    pii_lookup = build_pii_lookup(pii_result)
    dup_paths = build_duplicate_paths(dedup_result)

    # Create test suite
    testsuite = Element("testsuite")
    testsuite.set("name", "field-check")
    testsuite.set("tests", str(inventory.total_files))
    testsuite.set("time", f"{elapsed_seconds:.3f}")

    failures = 0
    errors = 0

    for entry in walk_result.files:
        path_str = str(entry.path)
        rel_path = try_relative(entry.path, walk_result.scan_root)

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
