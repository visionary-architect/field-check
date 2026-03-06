"""File inventory analysis — type detection, size/age/structure stats."""

from __future__ import annotations

import logging
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import filetype

from field_check.scanner import WalkResult

logger = logging.getLogger(__name__)

# Fallback MIME types for files that filetype.guess() can't detect (text-based files).
EXTENSION_MIME_MAP: dict[str, str] = {
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "text/json",
    ".jsonl": "text/json",
    ".xml": "text/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".rst": "text/x-rst",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "text/toml",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".conf": "text/plain",
    ".log": "text/plain",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".css": "text/css",
    ".sql": "text/x-sql",
    ".sh": "text/x-shellscript",
    ".bat": "text/x-bat",
    ".ps1": "text/x-powershell",
    ".r": "text/x-r",
    ".rb": "text/x-ruby",
    ".java": "text/x-java",
    ".c": "text/x-c",
    ".cpp": "text/x-c++",
    ".h": "text/x-c",
    ".go": "text/x-go",
    ".rs": "text/x-rust",
}

# Size bucket boundaries in bytes.
SIZE_BUCKETS: list[tuple[str, int, int]] = [
    ("<1 KB", 0, 1024),
    ("1-10 KB", 1024, 10 * 1024),
    ("10-100 KB", 10 * 1024, 100 * 1024),
    ("100 KB-1 MB", 100 * 1024, 1024 * 1024),
    ("1-10 MB", 1024 * 1024, 10 * 1024 * 1024),
    ("10-100 MB", 10 * 1024 * 1024, 100 * 1024 * 1024),
    (">100 MB", 100 * 1024 * 1024, float("inf")),
]

# Age bucket boundaries in seconds.
_DAY = 86400
_WEEK = 7 * _DAY
_MONTH = 30 * _DAY
_YEAR = 365 * _DAY

AGE_BUCKETS: list[tuple[str, float, float]] = [
    ("<1 day", 0, _DAY),
    ("1-7 days", _DAY, _WEEK),
    ("7-30 days", _WEEK, _MONTH),
    ("1-6 months", _MONTH, 6 * _MONTH),
    ("6-12 months", 6 * _MONTH, _YEAR),
    (">1 year", _YEAR, float("inf")),
]


@dataclass
class SizeBucket:
    """A single bucket in the size distribution."""

    label: str
    min_bytes: int
    max_bytes: float
    count: int = 0
    total_bytes: int = 0


@dataclass
class SizeDistribution:
    """Distribution of file sizes across buckets."""

    buckets: list[SizeBucket] = field(default_factory=list)
    min_size: int = 0
    max_size: int = 0
    median_size: int = 0
    mean_size: float = 0.0


@dataclass
class AgeBucket:
    """A single bucket in the age distribution."""

    label: str
    count: int = 0


@dataclass
class AgeDistribution:
    """Distribution of file ages across buckets."""

    buckets: list[AgeBucket] = field(default_factory=list)
    oldest: datetime | None = None
    newest: datetime | None = None


@dataclass
class DirectoryStructure:
    """Metrics about directory tree shape."""

    total_dirs: int = 0
    max_depth: int = 0
    avg_depth: float = 0.0
    max_breadth: int = 0
    avg_breadth: float = 0.0
    empty_dirs: int = 0


@dataclass
class InventoryResult:
    """Complete inventory analysis results."""

    total_files: int = 0
    total_size: int = 0
    type_counts: dict[str, int] = field(default_factory=dict)
    type_sizes: dict[str, int] = field(default_factory=dict)
    extension_counts: dict[str, int] = field(default_factory=dict)
    size_distribution: SizeDistribution = field(default_factory=SizeDistribution)
    age_distribution: AgeDistribution = field(default_factory=AgeDistribution)
    dir_structure: DirectoryStructure = field(default_factory=DirectoryStructure)
    file_types: dict[Path, str] = field(default_factory=dict)
    permission_errors: int = 0
    symlink_loops: int = 0
    excluded_count: int = 0
    type_detection_errors: int = 0


def _detect_file_type(filepath: Path) -> str:
    """Detect MIME type using magic bytes, falling back to extension.

    Short-circuits filetype.guess for known text extensions (no useful
    magic bytes) to avoid unnecessary file I/O.
    """
    ext = filepath.suffix.lower()
    ext_mime = EXTENSION_MIME_MAP.get(ext)
    if ext_mime is not None:
        return ext_mime

    try:
        guess = filetype.guess(str(filepath))
        if guess is not None:
            return guess.mime
    except (PermissionError, OSError):
        pass

    return "application/octet-stream"


def _compute_size_distribution(sizes: list[int]) -> SizeDistribution:
    """Bucket file sizes into standard ranges and compute stats."""
    if not sizes:
        return SizeDistribution(
            buckets=[SizeBucket(label=b[0], min_bytes=b[1], max_bytes=b[2]) for b in SIZE_BUCKETS]
        )

    buckets = [SizeBucket(label=b[0], min_bytes=b[1], max_bytes=b[2]) for b in SIZE_BUCKETS]
    for size in sizes:
        for bucket in buckets:
            if bucket.min_bytes <= size < bucket.max_bytes:
                bucket.count += 1
                bucket.total_bytes += size
                break

    return SizeDistribution(
        buckets=buckets,
        min_size=min(sizes),
        max_size=max(sizes),
        median_size=int(statistics.median(sizes)),
        mean_size=statistics.mean(sizes),
    )


def _compute_age_distribution(mtimes: list[float]) -> AgeDistribution:
    """Bucket file ages relative to current time."""
    if not mtimes:
        return AgeDistribution(
            buckets=[AgeBucket(label=b[0]) for b in AGE_BUCKETS]
        )

    now = time.time()
    buckets = [AgeBucket(label=b[0]) for b in AGE_BUCKETS]
    for mtime in mtimes:
        age = now - mtime
        for i, (_, min_age, max_age) in enumerate(AGE_BUCKETS):
            if min_age <= age < max_age:
                buckets[i].count += 1
                break

    return AgeDistribution(
        buckets=buckets,
        oldest=datetime.fromtimestamp(min(mtimes), tz=UTC),
        newest=datetime.fromtimestamp(max(mtimes), tz=UTC),
    )


def _compute_dir_structure(walk_result: WalkResult) -> DirectoryStructure:
    """Compute directory depth and breadth metrics from file paths."""
    if not walk_result.files:
        return DirectoryStructure(
            total_dirs=walk_result.total_dirs,
            empty_dirs=walk_result.empty_dirs,
        )

    # Count files per parent directory and compute depths
    files_per_dir: Counter[str] = Counter()
    depths: list[int] = []

    for entry in walk_result.files:
        parent = str(entry.relative_path.parent)
        files_per_dir[parent] += 1
        depth = len(entry.relative_path.parts) - 1  # depth of the file's directory
        depths.append(depth)

    breadths = list(files_per_dir.values())

    return DirectoryStructure(
        total_dirs=walk_result.total_dirs,
        max_depth=max(depths) if depths else 0,
        avg_depth=statistics.mean(depths) if depths else 0.0,
        max_breadth=max(breadths) if breadths else 0,
        avg_breadth=statistics.mean(breadths) if breadths else 0.0,
        empty_dirs=walk_result.empty_dirs,
    )


def analyze_inventory(
    walk_result: WalkResult,
    progress_callback: Callable[[int, int], None] | None = None,
) -> InventoryResult:
    """Analyze file inventory from walk results.

    Args:
        walk_result: Results from walk_directory().
        progress_callback: Called with (current, total) for progress display.

    Returns:
        Complete inventory analysis.
    """
    total = len(walk_result.files)
    type_counts: defaultdict[str, int] = defaultdict(int)
    type_sizes: defaultdict[str, int] = defaultdict(int)
    ext_counts: defaultdict[str, int] = defaultdict(int)
    file_types: dict[Path, str] = {}
    sizes: list[int] = []
    mtimes: list[float] = []
    detection_errors = 0

    for i, entry in enumerate(walk_result.files):
        mime = _detect_file_type(entry.path)
        file_types[entry.path] = mime
        type_counts[mime] += 1
        type_sizes[mime] += entry.size

        ext = entry.path.suffix.lower() or "(no extension)"
        ext_counts[ext] += 1

        sizes.append(entry.size)
        mtimes.append(entry.mtime)

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return InventoryResult(
        total_files=total,
        total_size=walk_result.total_size,
        type_counts=dict(type_counts),
        type_sizes=dict(type_sizes),
        extension_counts=dict(ext_counts),
        size_distribution=_compute_size_distribution(sizes),
        age_distribution=_compute_age_distribution(mtimes),
        dir_structure=_compute_dir_structure(walk_result),
        file_types=file_types,
        permission_errors=len(walk_result.permission_errors),
        symlink_loops=len(walk_result.symlink_loops),
        excluded_count=walk_result.excluded_count,
        type_detection_errors=detection_errors,
    )
