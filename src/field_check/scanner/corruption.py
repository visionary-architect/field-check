"""Corrupt, encrypted, and empty file detection."""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

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
STATUS_ENCRYPTED_OFFICE = "encrypted_office"
STATUS_TRUNCATED = "truncated"
STATUS_UNREADABLE = "unreadable"

# OOXML MIME types (DOCX, XLSX, PPTX)
_OOXML_MIMES: set[str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


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
    truncated_count: int = 0
    encrypted_count: int = 0
    unreadable_count: int = 0
    flagged_files: list[FileHealth] = field(default_factory=list)


def _detect_mime(filepath: Path) -> str:
    """Detect MIME type via puremagic then filetype (magic bytes).

    Falls back to empty string if detection fails.
    """
    try:
        import puremagic

        mime = puremagic.from_file(str(filepath), mime=True)
        if mime:
            return mime
    except ImportError:
        pass
    except Exception:
        pass

    try:
        import filetype

        kind = filetype.guess(str(filepath))
        return kind.mime if kind else ""
    except Exception:
        return ""


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

    Reads the first and last 4KB since the encryption dictionary
    reference is often in the trailer at the end of the file.
    """
    try:
        with open(filepath, "rb") as f:
            head = f.read(4096)
            f.seek(0, 2)
            size = f.tell()
            if size > 4096:
                f.seek(max(0, size - 4096))
                tail = f.read()
            else:
                tail = b""
        return b"/Encrypt" in head or b"/Encrypt" in tail
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


def _check_encrypted_office(filepath: Path) -> bool:
    """Check if an Office file is OOXML-encrypted using msoffcrypto-tool.

    Falls back gracefully if msoffcrypto-tool is not installed.
    """
    try:
        import msoffcrypto

        with open(filepath, "rb") as f:
            office_file = msoffcrypto.OfficeFile(f)
            return office_file.is_encrypted()
    except ImportError:
        return False  # Graceful: can't detect without library
    except Exception:
        return False  # Malformed or unsupported format


def _check_truncated_pdf(filepath: Path) -> bool:
    """Check if a PDF is truncated by looking for %%EOF marker.

    A well-formed PDF must end with a %%EOF marker near the end of the file.
    Missing %%EOF indicates the file was likely cut short (incomplete download,
    storage failure, etc.).
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last 1KB to find %%EOF
            read_size = min(1024, size)
            f.seek(max(0, size - read_size))
            tail = f.read()
        return b"%%EOF" not in tail
    except OSError:
        return False


def _check_docx_integrity(filepath: Path) -> str | None:
    """Check DOCX/XLSX/PPTX structural integrity via ZIP validation.

    Verifies CRC32 checksums and required OOXML entries.

    Returns:
        Error description if corrupt, None if valid.
    """
    import zipfile

    try:
        with zipfile.ZipFile(filepath) as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                return f"CRC32 mismatch in {bad_file}"
            names = zf.namelist()
            if "[Content_Types].xml" not in names:
                return "Missing [Content_Types].xml"
        return None
    except zipfile.BadZipFile:
        return "Invalid ZIP structure"
    except OSError:
        return None


def _check_truncated_image(filepath: Path, mime_type: str) -> bool:
    """Check if an image file is truncated by verifying end markers.

    JPEG files must end with 0xFF 0xD9 (EOI marker).
    PNG files must end with an IEND chunk.
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size < 16:
                return False  # Too small to validate
            read_size = min(64, size)
            f.seek(max(0, size - read_size))
            tail = f.read()
        if mime_type == "image/jpeg":
            return tail[-2:] != b"\xff\xd9"
        if mime_type == "image/png":
            return b"IEND" not in tail
        return False
    except OSError:
        return False


def _check_single_file(
    entry_path: Path,
    entry_size: int,
    known_mime: str | None = None,
) -> FileHealth:
    """Assess the health of a single file.

    Args:
        entry_path: Path to the file.
        entry_size: Known file size from walk.
        known_mime: Pre-computed MIME type from inventory (skips filetype.guess).

    Returns:
        FileHealth with status and detail.
    """
    # Empty check
    if entry_size == 0:
        return FileHealth(
            path=entry_path,
            status=STATUS_EMPTY,
            mime_type="",
            detail="File is empty (0 bytes)",
        )

    # Near-empty check
    if entry_size <= NEAR_EMPTY_THRESHOLD:
        return FileHealth(
            path=entry_path,
            status=STATUS_NEAR_EMPTY,
            mime_type="",
            detail=f"File is very small ({entry_size} bytes)",
        )

    # Read header for magic byte checks
    try:
        with open(entry_path, "rb") as f:
            header = f.read(8)
    except (PermissionError, OSError):
        return FileHealth(
            path=entry_path,
            status=STATUS_UNREADABLE,
            mime_type="",
            detail="Could not read file",
        )

    # Reuse pre-computed MIME type or detect fresh
    mime_type = known_mime if known_mime is not None else _detect_mime(entry_path)

    # Magic byte validation - only for types we have signatures for
    if mime_type in MAGIC_SIGNATURES and not _check_magic_bytes(header, mime_type):
        return FileHealth(
            path=entry_path,
            status=STATUS_CORRUPT,
            mime_type=mime_type,
            detail=f"Header mismatch for {mime_type}",
        )

    # Encrypted PDF check
    if header.startswith(b"%PDF") and _check_encrypted_pdf(entry_path):
        return FileHealth(
            path=entry_path,
            status=STATUS_ENCRYPTED_PDF,
            mime_type=mime_type or "application/pdf",
            detail="PDF contains /Encrypt dictionary",
        )

    # Encrypted ZIP check
    if header.startswith(b"PK\x03\x04") and _check_encrypted_zip(entry_path):
        return FileHealth(
            path=entry_path,
            status=STATUS_ENCRYPTED_ZIP,
            mime_type=mime_type or "application/zip",
            detail="ZIP has encryption flag set",
        )

    # OOXML Office encryption check (requires msoffcrypto-tool)
    if mime_type in _OOXML_MIMES and _check_encrypted_office(entry_path):
        return FileHealth(
            path=entry_path,
            status=STATUS_ENCRYPTED_OFFICE,
            mime_type=mime_type,
            detail="OOXML file is encrypted",
        )

    # Truncation checks
    if header.startswith(b"%PDF") and _check_truncated_pdf(entry_path):
        return FileHealth(
            path=entry_path,
            status=STATUS_TRUNCATED,
            mime_type=mime_type or "application/pdf",
            detail="PDF missing %%EOF marker (likely truncated)",
        )

    # DOCX/XLSX/PPTX integrity (ZIP-based Office formats)
    if header.startswith(b"PK\x03\x04") and mime_type in _OOXML_MIMES:
        integrity_error = _check_docx_integrity(entry_path)
        if integrity_error:
            return FileHealth(
                path=entry_path,
                status=STATUS_CORRUPT,
                mime_type=mime_type,
                detail=f"OOXML integrity: {integrity_error}",
            )

    # Image truncation checks
    if mime_type in ("image/jpeg", "image/png") and _check_truncated_image(entry_path, mime_type):
        return FileHealth(
            path=entry_path,
            status=STATUS_TRUNCATED,
            mime_type=mime_type,
            detail=f"Missing end marker for {mime_type}",
        )

    return FileHealth(
        path=entry_path,
        status=STATUS_OK,
        mime_type=mime_type,
        detail="",
    )


def check_corruption(
    walk_result: WalkResult,
    progress_callback: Callable[[int, int], None] | None = None,
    file_types: dict[Path, str] | None = None,
) -> CorruptionResult:
    """Check all files for corruption, encryption, and emptiness.

    Args:
        walk_result: Results from directory walk.
        progress_callback: Called with (current, total) after each file.
        file_types: Pre-computed MIME types from inventory (avoids
            redundant filetype.guess calls).

    Returns:
        CorruptionResult with counts and flagged files.
    """
    total = len(walk_result.files)
    result = CorruptionResult(total_checked=total)

    for i, entry in enumerate(walk_result.files):
        known_mime = file_types.get(entry.path) if file_types else None
        health = _check_single_file(entry.path, entry.size, known_mime)

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
        elif health.status == STATUS_TRUNCATED:
            result.truncated_count += 1
            result.flagged_files.append(health)
        elif health.status in (
            STATUS_ENCRYPTED_PDF,
            STATUS_ENCRYPTED_ZIP,
            STATUS_ENCRYPTED_OFFICE,
        ):
            result.encrypted_count += 1
            result.flagged_files.append(health)
        elif health.status == STATUS_UNREADABLE:
            result.unreadable_count += 1
            result.flagged_files.append(health)

        if progress_callback is not None:
            progress_callback(i + 1, total)

    return result
