"""BLAKE3 content hashing and exact duplicate detection."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import blake3

from field_check.scanner import WalkResult

logger = logging.getLogger(__name__)

# 64KB read chunks balance memory vs syscall overhead
_CHUNK_SIZE = 65536

# Max worker threads for parallel hashing
_MAX_WORKERS = 4


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
    max_workers: int | None = None,
) -> DedupResult:
    """Hash all files and detect exact duplicates.

    Uses ThreadPoolExecutor for parallel hashing — BLAKE3's Rust backend
    releases the GIL, so threads can overlap I/O and CPU work.

    Args:
        walk_result: Results from directory walk.
        progress_callback: Called with (current, total) after each file.
        max_workers: Max hash threads (default: min(4, cpu_count)).

    Returns:
        DedupResult with duplicate groups and statistics.
    """
    total = len(walk_result.files)
    hash_map: dict[str, list[tuple[Path, int]]] = {}
    hash_errors = 0

    # Pre-filter: group by size, only hash files that share a size
    # with at least one other file. Unique sizes can never be duplicates.
    size_groups: dict[int, list] = defaultdict(list)
    for entry in walk_result.files:
        size_groups[entry.size].append(entry)

    candidate_entries = [
        entry
        for entries in size_groups.values()
        if len(entries) >= 2
        for entry in entries
    ]

    candidate_set = {id(e) for e in candidate_entries}
    completed = 0

    # Report progress for non-candidates (skipped, no hashing needed)
    if progress_callback is not None:
        for entry in walk_result.files:
            if id(entry) not in candidate_set:
                completed += 1
                progress_callback(completed, total)

    # Hash candidates in parallel (BLAKE3 releases the GIL)
    if candidate_entries:
        workers = max_workers or min(_MAX_WORKERS, os.cpu_count() or 1)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_entry = {
                pool.submit(_hash_file, entry.path): entry
                for entry in candidate_entries
            }

            for future in as_completed(future_to_entry):
                entry = future_to_entry[future]
                try:
                    file_hash = future.result()
                    if file_hash not in hash_map:
                        hash_map[file_hash] = []
                    hash_map[file_hash].append((entry.path, entry.size))
                except (PermissionError, OSError):
                    logger.debug("Could not hash file: %s", entry.path)
                    hash_errors += 1

                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total)

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
    # Unique files = those with unique sizes (never hashed) + unique hashes
    unique_by_size = sum(1 for g in size_groups.values() if len(g) == 1)
    unique_files = unique_by_size + len(hash_map)
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
