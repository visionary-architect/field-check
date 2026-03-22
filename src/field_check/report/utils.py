"""Shared formatting utilities for report renderers."""

from __future__ import annotations

from pathlib import Path

from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.encoding import EncodingResult
from field_check.scanner.language import LanguageResult
from field_check.scanner.pii import PIIScanResult


def format_size(size_bytes: int | float) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def format_duration(seconds: float) -> str:
    """Format elapsed seconds into human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def try_relative(p: str | Path, root: Path) -> str:
    """Return path relative to root if possible, otherwise the original."""
    try:
        return str(Path(p).relative_to(root))
    except (ValueError, TypeError):
        return str(p)


def try_relative_forward(p: str | Path, root: Path) -> str:
    """Return path relative to root with forward slashes (for SARIF URIs)."""
    try:
        return str(Path(p).relative_to(root)).replace("\\", "/")
    except (ValueError, TypeError):
        return str(p).replace("\\", "/")


def build_duplicate_paths(dedup: DedupResult | None) -> set[str]:
    """Build set of paths that are duplicates."""
    paths: set[str] = set()
    if dedup is None:
        return paths
    for group in dedup.duplicate_groups:
        for p in group.paths:
            paths.add(str(p))
    return paths


def build_hash_lookup(dedup: DedupResult | None) -> dict[str, str]:
    """Build path -> blake3 hash lookup from dedup result."""
    lookup: dict[str, str] = {}
    if dedup is None:
        return lookup
    for group in dedup.duplicate_groups:
        for p in group.paths:
            lookup[str(p)] = group.hash
    return lookup


def build_health_lookup(corruption: CorruptionResult | None) -> dict[str, str]:
    """Build path -> health status lookup."""
    lookup: dict[str, str] = {}
    if corruption is None:
        return lookup
    for fh in corruption.flagged_files:
        lookup[str(fh.path)] = fh.status
    return lookup


def build_corruption_detail_lookup(
    corruption: CorruptionResult | None,
) -> dict[str, tuple[str, str]]:
    """Build path -> (status, detail) lookup."""
    lookup: dict[str, tuple[str, str]] = {}
    if corruption is None:
        return lookup
    for fh in corruption.flagged_files:
        lookup[str(fh.path)] = (fh.status, fh.detail)
    return lookup


def build_pii_lookup(pii: PIIScanResult | None) -> dict[str, list[str]]:
    """Build path -> list of PII pattern types lookup."""
    lookup: dict[str, list[str]] = {}
    if pii is None:
        return lookup
    for fr in pii.file_results:
        if fr.matches_by_type:
            lookup[fr.path] = list(fr.matches_by_type.keys())
    return lookup


def build_language_lookup(language: LanguageResult | None) -> dict[str, str]:
    """Build path -> detected language lookup."""
    lookup: dict[str, str] = {}
    if language is None:
        return lookup
    for fr in language.file_results:
        lookup[fr.path] = fr.language
    return lookup


def build_encoding_lookup(encoding: EncodingResult | None) -> dict[str, str]:
    """Build path -> detected encoding lookup."""
    lookup: dict[str, str] = {}
    if encoding is None:
        return lookup
    for fr in encoding.file_results:
        lookup[fr.path] = fr.encoding
    return lookup
