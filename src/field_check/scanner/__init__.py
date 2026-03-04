"""Corpus scanning modules — file walker and analysis."""

from __future__ import annotations

import logging
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from field_check.config import FieldCheckConfig, should_exclude

logger = logging.getLogger(__name__)


@dataclass
class FileEntry:
    """Metadata for a single file discovered during scanning."""

    path: Path
    relative_path: Path
    size: int
    mtime: float
    # On Unix, ctime = inode change time (NOT creation time).
    # On Windows, ctime = file creation time.
    # Age analysis should primarily use mtime.
    ctime: float
    is_symlink: bool


@dataclass
class WalkResult:
    """Results from walking a directory tree."""

    files: list[FileEntry] = field(default_factory=list)
    total_size: int = 0
    total_dirs: int = 0
    empty_dirs: int = 0
    permission_errors: list[Path] = field(default_factory=list)
    symlink_loops: list[Path] = field(default_factory=list)
    excluded_count: int = 0
    scan_root: Path = field(default_factory=Path)


def _long_path(path: str) -> str:
    """Prefix with \\\\?\\ on Windows for paths exceeding 259 chars."""
    if sys.platform == "win32" and len(path) > 259 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path


def walk_directory(
    root: Path,
    config: FieldCheckConfig,
    progress_callback: Callable[[int], None] | None = None,
) -> WalkResult:
    """Walk a directory tree and collect file metadata.

    Args:
        root: Root directory to scan.
        config: Configuration with exclude patterns.
        progress_callback: Called with current file count after each file.

    Returns:
        WalkResult with all discovered files and statistics.

    Raises:
        FileNotFoundError: If root does not exist.
        NotADirectoryError: If root is not a directory.
    """
    root = Path(root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {root}")

    result = WalkResult(scan_root=root)
    # Track visited directories by (dev, inode) to detect symlink loops.
    # On Windows where inode may be 0, fall back to resolved path tracking.
    visited_dirs: set[tuple[int, int]] = set()
    visited_paths: set[str] = set()
    file_count = 0

    for dirpath_str, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirpath = Path(dirpath_str)
        rel_dir = dirpath.relative_to(root)

        # Check if this directory should be excluded
        if str(rel_dir) != "." and should_exclude(str(rel_dir), config.exclude):
            result.excluded_count += 1
            dirnames.clear()
            continue

        result.total_dirs += 1

        # Detect symlink loops on the current directory
        try:
            dir_stat = os.stat(_long_path(dirpath_str))
            dev_ino = (dir_stat.st_dev, dir_stat.st_ino)
            if dir_stat.st_ino != 0:
                if dev_ino in visited_dirs:
                    result.symlink_loops.append(dirpath)
                    dirnames.clear()
                    continue
                visited_dirs.add(dev_ino)
            else:
                # Windows fallback: use resolved path
                resolved = str(dirpath.resolve())
                if resolved in visited_paths:
                    result.symlink_loops.append(dirpath)
                    dirnames.clear()
                    continue
                visited_paths.add(resolved)
        except PermissionError:
            result.permission_errors.append(dirpath)
            dirnames.clear()
            continue
        except OSError:
            logger.debug("OSError stating directory: %s", dirpath)
            dirnames.clear()
            continue

        # Filter excluded subdirectories in-place to prevent descending
        filtered_dirs = []
        for d in dirnames:
            rel_sub = rel_dir / d if str(rel_dir) != "." else Path(d)
            if should_exclude(str(rel_sub), config.exclude):
                result.excluded_count += 1
            else:
                # Check if subdirectory is a symlink that would loop
                subdir_path = dirpath / d
                if subdir_path.is_symlink():
                    try:
                        resolved = str(subdir_path.resolve())
                        # If symlink points to an ancestor, it's a loop
                        if resolved == str(root) or str(root).startswith(resolved + os.sep):
                            result.symlink_loops.append(subdir_path)
                            continue
                        if resolved in visited_paths or resolved.startswith(str(root)):
                            # Symlink to somewhere we've already visited or within scan tree
                            target_stat = os.stat(resolved)
                            if (
                                target_stat.st_ino != 0
                                and (target_stat.st_dev, target_stat.st_ino) in visited_dirs
                            ):
                                result.symlink_loops.append(subdir_path)
                                continue
                    except OSError:
                        pass
                filtered_dirs.append(d)
        dirnames[:] = filtered_dirs

        # Track whether this directory has any regular files
        has_files = False

        for filename in filenames:
            filepath = dirpath / filename
            rel_path = rel_dir / filename if str(rel_dir) != "." else Path(filename)

            if should_exclude(str(rel_path), config.exclude):
                result.excluded_count += 1
                continue

            try:
                fpath_str = _long_path(str(filepath))
                lstat = os.lstat(fpath_str)

                # Skip special files (devices, pipes, sockets)
                if not stat.S_ISREG(lstat.st_mode) and not stat.S_ISLNK(lstat.st_mode):
                    continue

                is_symlink = stat.S_ISLNK(lstat.st_mode)
                if is_symlink:
                    # Get the actual file stat for size/times
                    try:
                        fstat = os.stat(fpath_str)
                        if not stat.S_ISREG(fstat.st_mode):
                            continue
                    except OSError:
                        # Broken symlink
                        continue
                else:
                    fstat = lstat

                entry = FileEntry(
                    path=filepath,
                    relative_path=rel_path,
                    size=fstat.st_size,
                    mtime=fstat.st_mtime,
                    ctime=fstat.st_ctime,
                    is_symlink=is_symlink,
                )
                result.files.append(entry)
                result.total_size += fstat.st_size
                has_files = True
                file_count += 1

                if progress_callback is not None:
                    progress_callback(file_count)

            except PermissionError:
                result.permission_errors.append(filepath)
            except OSError:
                logger.debug("OSError accessing file: %s", filepath)

        if not has_files:
            result.empty_dirs += 1

    return result
