"""SARIF (Static Analysis Results Interchange Format) report renderer.

Generates SARIF v2.1.0 JSON output for security tool integration.
No external dependencies — SARIF is just JSON with a defined schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from field_check import __version__
from field_check.report.utils import try_relative_forward
from field_check.scanner import WalkResult
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.inventory import InventoryResult
from field_check.scanner.mojibake import MojibakeResult
from field_check.scanner.pii import PIIScanResult

SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
SARIF_VERSION = "2.1.0"

# Rule definitions for Field Check findings
_RULES = [
    {
        "id": "FC001",
        "name": "CorruptFile",
        "shortDescription": {"text": "File is corrupt or has structural issues"},
        "defaultConfiguration": {"level": "error"},
    },
    {
        "id": "FC002",
        "name": "TruncatedFile",
        "shortDescription": {"text": "File appears truncated (missing end marker)"},
        "defaultConfiguration": {"level": "error"},
    },
    {
        "id": "FC003",
        "name": "EncryptedFile",
        "shortDescription": {"text": "File is encrypted and cannot be processed"},
        "defaultConfiguration": {"level": "warning"},
    },
    {
        "id": "FC004",
        "name": "EmptyFile",
        "shortDescription": {"text": "File is empty (0 bytes)"},
        "defaultConfiguration": {"level": "warning"},
    },
    {
        "id": "FC005",
        "name": "PIIRiskIndicator",
        "shortDescription": {"text": "File contains PII risk indicators"},
        "defaultConfiguration": {"level": "warning"},
    },
    {
        "id": "FC006",
        "name": "DuplicateFile",
        "shortDescription": {"text": "File is an exact duplicate of another file"},
        "defaultConfiguration": {"level": "note"},
    },
    {
        "id": "FC007",
        "name": "EncodingDamage",
        "shortDescription": {"text": "File contains encoding damage (mojibake)"},
        "defaultConfiguration": {"level": "note"},
    },
]

# Map corruption statuses to SARIF rule IDs
_STATUS_TO_RULE: dict[str, str] = {
    "corrupt": "FC001",
    "truncated": "FC002",
    "encrypted_pdf": "FC003",
    "encrypted_zip": "FC003",
    "encrypted_office": "FC003",
    "empty": "FC004",
    "near_empty": "FC004",
    "unreadable": "FC001",
}


def render_sarif_report(
    inventory: InventoryResult,
    walk_result: WalkResult,
    corruption_result: CorruptionResult | None = None,
    pii_result: PIIScanResult | None = None,
    dedup_result: DedupResult | None = None,
    mojibake_result: MojibakeResult | None = None,
    **_kwargs: object,
) -> str:
    """Render findings as SARIF v2.1.0 JSON.

    Maps scanner findings to SARIF rules:
    - FC001: Corrupt files (error)
    - FC002: Truncated files (error)
    - FC003: Encrypted files (warning)
    - FC004: Empty/near-empty files (warning)
    - FC005: PII risk indicators (warning) — counts only, no content (Invariant 3)
    - FC006: Duplicate files (note)
    - FC007: Encoding damage (note)

    Returns:
        Pretty-printed SARIF JSON string.
    """
    results: list[dict] = []

    # Corruption findings
    if corruption_result is not None:
        for fh in corruption_result.flagged_files:
            rule_id = _STATUS_TO_RULE.get(fh.status)
            if rule_id is None:
                continue
            results.append(
                _make_result(
                    rule_id=rule_id,
                    message=fh.detail,
                    path=try_relative_forward(fh.path, walk_result.scan_root),
                )
            )

    # PII findings — counts only, NO matched content (Invariant 3)
    if pii_result is not None:
        for fr in pii_result.file_results:
            if not fr.matches_by_type:
                continue
            types = list(fr.matches_by_type.keys())
            total = sum(fr.matches_by_type.values())
            results.append(
                _make_result(
                    rule_id="FC005",
                    message=f"{total} PII risk indicator(s) found: {', '.join(types)}",
                    path=try_relative_forward(Path(fr.path), walk_result.scan_root),
                )
            )

    # Duplicate findings
    if dedup_result is not None:
        for group in dedup_result.duplicate_groups:
            # Skip the first path (the "original"), flag the rest as duplicates
            orig = try_relative_forward(group.paths[0], walk_result.scan_root)
            for dup_path in group.paths[1:]:
                results.append(
                    _make_result(
                        rule_id="FC006",
                        message=f"Exact duplicate of {orig}",
                        path=try_relative_forward(dup_path, walk_result.scan_root),
                    )
                )

    # Mojibake findings
    if mojibake_result is not None:
        for path in mojibake_result.mojibake_files:
            results.append(
                _make_result(
                    rule_id="FC007",
                    message="File contains encoding damage (mojibake)",
                    path=try_relative_forward(Path(path), walk_result.scan_root),
                )
            )

    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "field-check",
                        "version": __version__,
                        "informationUri": "https://github.com/usefield/field-check",
                        "rules": _RULES,
                    },
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "commandLine": "field-check scan",
                    },
                ],
            },
        ],
    }

    return json.dumps(sarif, indent=2, ensure_ascii=False)


def _make_result(rule_id: str, message: str, path: str | Path) -> dict:
    """Create a single SARIF result entry."""
    level_map = {
        "FC001": "error",
        "FC002": "error",
        "FC003": "warning",
        "FC004": "warning",
        "FC005": "warning",
        "FC006": "note",
        "FC007": "note",
    }
    return {
        "ruleId": rule_id,
        "level": level_map.get(rule_id, "note"),
        "message": {"text": message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": str(path).replace("\\", "/")},
                },
            },
        ],
    }
