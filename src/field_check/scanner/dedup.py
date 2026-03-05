"""BLAKE3 content hashing and exact duplicate detection."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import blake3

from field_check.scanner import WalkResult

logger = logging.getLogger(__name__)

# 64KB read chunks balance memory vs syscall overhead
_CHUNK_SIZE = 65536


@dataclass
class DuplicateGroup:
    """A group of files with identical content."""

    hash: str
    size: int
    paths: list[Path] = field(default_factory=list)


@dataclass
class DedupResult:
    """Results from duplicate detection scan."""

    total_hashed: int = 0
    hash_errors: int = 0
    unique_files: int = 0
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    duplicate_file_count: int = 0
    duplicate_bytes: int = 0
    duplicate_percentage: float = 0.0


def _hash_file(filepath: Path) -> str:
    """Compute BLAKE3 hash of a file.

    Args:
        filepath: Path to the file to hash.

    Returns:
        Hex digest string.
    """
    hasher = blake3.blake3()
    with open(filepath, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_hashes(
    walk_result: WalkResult,
    progress_callback: Callable[[int, int], None] | None = None,
) -> DedupResult:
    """Hash all files and detect exact duplicates.

    Args:
        walk_result: Results from directory walk.
        progress_callback: Called with (current, total) after each file.

    Returns:
        DedupResult with duplicate groups and statistics.
    """
    total = len(walk_result.files)
    hash_map: dict[str, list[tuple[Path, int]]] = {}
    hash_errors = 0

    for i, entry in enumerate(walk_result.files):
        try:
            file_hash = _hash_file(entry.path)
            if file_hash not in hash_map:
                hash_map[file_hash] = []
            hash_map[file_hash].append((entry.path, entry.size))
        except (PermissionError, OSError):
            logger.debug("Could not hash file: %s", entry.path)
            hash_errors += 1

        if progress_callback is not None:
            progress_callback(i + 1, total)

    # Build duplicate groups (2+ files with same hash)
    duplicate_groups: list[DuplicateGroup] = []
    for file_hash, entries in hash_map.items():
        if len(entries) >= 2:
            paths = [p for p, _ in entries]
            size = entries[0][1]
            duplicate_groups.append(
                DuplicateGroup(hash=file_hash, size=size, paths=paths)
            )

    total_hashed = total - hash_errors
    unique_files = len(hash_map)
    duplicate_file_count = sum(len(g.paths) for g in duplicate_groups)
    duplicate_bytes = sum(
        g.size * (len(g.paths) - 1) for g in duplicate_groups
    )
    duplicate_percentage = (
        (duplicate_file_count / total_hashed * 100) if total_hashed else 0.0
    )

    return DedupResult(
        total_hashed=total_hashed,
        hash_errors=hash_errors,
        unique_files=unique_files,
        duplicate_groups=duplicate_groups,
        duplicate_file_count=duplicate_file_count,
        duplicate_bytes=duplicate_bytes,
        duplicate_percentage=duplicate_percentage,
    )
