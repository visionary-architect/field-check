"""Shared test fixtures for Field Check."""

from __future__ import annotations

import os
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

from field_check.config import FieldCheckConfig


def create_minimal_pdf(path: Path) -> None:
    """Write minimal valid PDF bytes (enough for filetype to detect)."""
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"xref\n0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000052 00000 n \n"
        b"trailer<</Size 3/Root 1 0 R>>\n"
        b"startxref\n95\n%%EOF"
    )
    path.write_bytes(pdf_bytes)


def create_minimal_png(path: Path) -> None:
    """Write minimal valid PNG bytes (enough for filetype to detect)."""
    # PNG signature
    signature = b"\x89PNG\r\n\x1a\n"
    # Minimal IHDR chunk: 1x1 pixel, 8-bit RGB
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    # Minimal IDAT chunk
    raw_data = zlib.compress(b"\x00\x00\x00\x00")
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + raw_data) & 0xFFFFFFFF)
    idat = struct.pack(">I", len(raw_data)) + b"IDAT" + raw_data + idat_crc
    # IEND chunk
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc

    path.write_bytes(signature + ihdr + idat + iend)


@pytest.fixture()
def tmp_corpus(tmp_path: Path) -> Path:
    """Create a temporary directory with a known set of test files."""
    # Text file
    (tmp_path / "doc.txt").write_text("Hello world. " * 8, encoding="utf-8")

    # PDF file
    create_minimal_pdf(tmp_path / "report.pdf")

    # CSV file
    (tmp_path / "data.csv").write_text(
        "name,age,city\nAlice,30,NYC\nBob,25,LA\n", encoding="utf-8"
    )

    # PNG image
    create_minimal_png(tmp_path / "image.png")

    # Empty file
    (tmp_path / "empty.txt").write_bytes(b"")

    # Nested directory structure
    nested = tmp_path / "nested" / "deep"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_text("nested content", encoding="utf-8")

    # Larger binary file (~10KB)
    (tmp_path / "large.bin").write_bytes(os.urandom(10240))

    # Empty subdirectory (no files)
    (tmp_path / "empty_dir").mkdir()

    return tmp_path


@pytest.fixture()
def tmp_corpus_with_symlinks(tmp_corpus: Path) -> Path:
    """Add symlinks to the test corpus."""
    if sys.platform == "win32":
        pytest.skip("Symlink tests require admin on Windows")

    # Valid symlink to a file
    (tmp_corpus / "link_to_doc.txt").symlink_to(tmp_corpus / "doc.txt")

    # Symlink loop: directory pointing to parent
    loop_dir = tmp_corpus / "loop_target"
    loop_dir.mkdir()
    (loop_dir / "loop_back").symlink_to(tmp_corpus, target_is_directory=True)

    return tmp_corpus


@pytest.fixture()
def tmp_corpus_with_config(tmp_corpus: Path) -> Path:
    """Add a .field-check.yaml to the test corpus."""
    config_content = 'exclude:\n  - "*.bin"\n  - "nested"\n'
    (tmp_corpus / ".field-check.yaml").write_text(config_content, encoding="utf-8")
    return tmp_corpus


@pytest.fixture()
def default_config() -> FieldCheckConfig:
    """Return a FieldCheckConfig with default values."""
    return FieldCheckConfig()


def create_minimal_zip(path: Path) -> None:
    """Write a valid ZIP file with a small text entry."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("test.txt", "hello from zip")


def create_encrypted_zip(path: Path) -> None:
    """Write a ZIP file with the encryption flag set in the local header.

    Creates a valid ZIP structure, then patches byte 6 to set bit 0
    (encryption flag) in the general purpose bit flag.
    """
    create_minimal_zip(path)
    data = bytearray(path.read_bytes())
    # Local file header general purpose bit flag is at offset 6
    flags = struct.unpack_from("<H", data, 6)[0]
    flags |= 0x01  # Set encryption bit
    struct.pack_into("<H", data, 6, flags)
    path.write_bytes(bytes(data))


def create_corrupt_pdf(path: Path) -> None:
    """Write a file with .pdf extension but PNG header bytes."""
    create_minimal_png(path)


def create_encrypted_pdf(path: Path) -> None:
    """Write a minimal PDF that contains an /Encrypt dictionary marker."""
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"3 0 obj<</Type/Encryption/Filter/Standard/V 1"
        b"/R 2/O(owner)/U(user)/P -3904>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000052 00000 n \n"
        b"0000000095 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R/Encrypt 3 0 R>>\n"
        b"startxref\n200\n%%EOF"
    )
    path.write_bytes(pdf_bytes)


@pytest.fixture()
def tmp_corpus_with_duplicates(tmp_path: Path) -> Path:
    """Create a corpus with known duplicate files."""
    # 3 identical text files
    text_content = "This is duplicate content for testing purposes.\n"
    (tmp_path / "file_a.txt").write_text(text_content, encoding="utf-8")
    (tmp_path / "file_b.txt").write_text(text_content, encoding="utf-8")
    (tmp_path / "file_c.txt").write_text(text_content, encoding="utf-8")

    # 2 identical binary files
    binary_content = b"\x00\x01\x02\x03" * 256  # 1KB
    (tmp_path / "data1.bin").write_bytes(binary_content)
    (tmp_path / "data2.bin").write_bytes(binary_content)

    # 1 unique file
    (tmp_path / "unique.txt").write_text("I am unique.", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def tmp_corpus_with_issues(tmp_path: Path) -> Path:
    """Create a corpus with various file health issues."""
    # Empty file
    (tmp_path / "empty.dat").write_bytes(b"")

    # Near-empty file (10 bytes)
    (tmp_path / "tiny.dat").write_bytes(b"0123456789")

    # Corrupt PDF (PNG header in .pdf extension)
    create_corrupt_pdf(tmp_path / "corrupt.pdf")

    # Encrypted PDF
    create_encrypted_pdf(tmp_path / "encrypted.pdf")

    # Encrypted ZIP
    create_encrypted_zip(tmp_path / "encrypted.zip")

    # Normal valid PDF
    create_minimal_pdf(tmp_path / "valid.pdf")

    # Normal valid PNG
    create_minimal_png(tmp_path / "valid.png")

    return tmp_path
