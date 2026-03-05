"""Corrupt, encrypted, and empty file detection."""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import filetype

from field_check.scanner import WalkResult

logger = logging.getLogger(__name__)

# Expected magic bytes per MIME type
MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],
    "application/zip": [b"PK\x03\x04", b"PK\x05\x06"],
    "image/png": [b"\x89PNG"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "application/gzip": [b"\x1f\x8b"],
}

# Files under this size are considered "near-empty"
NEAR_EMPTY_THRESHOLD: int = 50

# Status constants
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_NEAR_EMPTY = "near_empty"
STATUS_CORRUPT = "corrupt"
STATUS_ENCRYPTED_PDF = "encrypted_pdf"
STATUS_ENCRYPTED_ZIP = "encrypted_zip"
STATUS_UNREADABLE = "unreadable"


@dataclass
class FileHealth:
    """Health assessment for a single file."""

    path: Path
    status: str
    mime_type: str
    detail: str


@dataclass
class CorruptionResult:
    """Results from corruption detection scan."""

    total_checked: int = 0
    ok_count: int = 0
    empty_count: int = 0
    near_empty_count: int = 0
    corrupt_count: int = 0
    encrypted_count: int = 0
    unreadable_count: int = 0
    flagged_files: list[FileHealth] = field(default_factory=list)


def _detect_mime(filepath: Path) -> str:
    """Detect MIME type via filetype (magic bytes).

    Falls back to empty string if detection fails.
    """
    kind = filetype.guess(str(filepath))
    return kind.mime if kind else ""


def _check_magic_bytes(header: bytes, mime_type: str) -> bool:
    """Check if file header matches expected magic bytes for its MIME type.

    Returns True if the header matches (file is valid), or if we have
    no signature for this MIME type (can't validate, assume ok).
    """
    signatures = MAGIC_SIGNATURES.get(mime_type)
    if signatures is None:
        return True
    return any(header.startswith(sig) for sig in signatures)


def _check_encrypted_pdf(filepath: Path) -> bool:
    """Check if a PDF file contains an /Encrypt dictionary.

    Reads the first 4KB and searches for the /Encrypt marker.
    """
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(4096)
        return b"/Encrypt" in chunk
    except OSError:
        return False


def _check_encrypted_zip(filepath: Path) -> bool:
    """Check if a ZIP file has the encryption flag set.

    Reads bytes 6-7 (general purpose bit flag) from the local file header.
    Bit 0 indicates encryption.
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(6)
            flag_bytes = f.read(2)
            if len(flag_bytes) < 2:
                return False
            flags = struct.unpack("<H", flag_bytes)[0]
            return bool(flags & 0x01)
    except OSError:
        return False


def _check_single_file(
    entry_path: Path, entry_size: int,
) -> FileHealth:
    """Assess the health of a single file.

    Args:
        entry_path: Path to the file.
        entry_size: Known file size from walk.

    Returns:
        FileHealth with status and detail.
    """
    # Empty check
    if entry_size == 0:
        return FileHealth(
            path=entry_path, status=STATUS_EMPTY,
            mime_type="", detail="File is empty (0 bytes)",
        )

    # Near-empty check
    if entry_size <= NEAR_EMPTY_THRESHOLD:
        return FileHealth(
            path=entry_path, status=STATUS_NEAR_EMPTY,
            mime_type="", detail=f"File is very small ({entry_size} bytes)",
        )

    # Read header for magic byte checks
    try:
        with open(entry_path, "rb") as f:
            header = f.read(8)
    except (PermissionError, OSError):
        return FileHealth(
            path=entry_path, status=STATUS_UNREADABLE,
            mime_type="", detail="Could not read file",
        )

    # Detect MIME type
    mime_type = _detect_mime(entry_path)

    # Magic byte validation - only for types we have signatures for
    if mime_type in MAGIC_SIGNATURES and not _check_magic_bytes(header, mime_type):
        return FileHealth(
            path=entry_path, status=STATUS_CORRUPT,
            mime_type=mime_type,
            detail=f"Header mismatch for {mime_type}",
        )

    # Encrypted PDF check
    if header.startswith(b"%PDF") and _check_encrypted_pdf(entry_path):
        return FileHealth(
            path=entry_path, status=STATUS_ENCRYPTED_PDF,
            mime_type=mime_type or "application/pdf",
            detail="PDF contains /Encrypt dictionary",
        )

    # Encrypted ZIP check
    if header.startswith(b"PK\x03\x04") and _check_encrypted_zip(entry_path):
        return FileHealth(
            path=entry_path, status=STATUS_ENCRYPTED_ZIP,
            mime_type=mime_type or "application/zip",
            detail="ZIP has encryption flag set",
        )

    return FileHealth(
        path=entry_path, status=STATUS_OK,
        mime_type=mime_type, detail="",
    )


def check_corruption(
    walk_result: WalkResult,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CorruptionResult:
    """Check all files for corruption, encryption, and emptiness.

    Args:
        walk_result: Results from directory walk.
        progress_callback: Called with (current, total) after each file.

    Returns:
        CorruptionResult with counts and flagged files.
    """
    total = len(walk_result.files)
    result = CorruptionResult(total_checked=total)

    for i, entry in enumerate(walk_result.files):
        health = _check_single_file(entry.path, entry.size)

        if health.status == STATUS_OK:
            result.ok_count += 1
        elif health.status == STATUS_EMPTY:
            result.empty_count += 1
            result.flagged_files.append(health)
        elif health.status == STATUS_NEAR_EMPTY:
            result.near_empty_count += 1
            result.flagged_files.append(health)
        elif health.status == STATUS_CORRUPT:
            result.corrupt_count += 1
            result.flagged_files.append(health)
        elif health.status in (STATUS_ENCRYPTED_PDF, STATUS_ENCRYPTED_ZIP):
            result.encrypted_count += 1
            result.flagged_files.append(health)
        elif health.status == STATUS_UNREADABLE:
            result.unreadable_count += 1
            result.flagged_files.append(health)

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return result
