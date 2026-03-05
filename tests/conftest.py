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


def create_pdf_with_text(path: Path, text: str = "Hello world", pages: int = 1) -> None:
    """Create a PDF with actual text content that pdfplumber can extract."""
    # Build a minimal but valid PDF with text content streams
    objects: list[bytes] = []
    offsets: list[int] = []
    pos = 0

    header = b"%PDF-1.4\n"
    pos = len(header)

    # Object 1: Catalog
    offsets.append(pos)
    obj1 = b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    objects.append(obj1)
    pos += len(obj1)

    # Object 2: Pages
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    offsets.append(pos)
    obj2 = f"2 0 obj<</Type/Pages/Kids[{kids}]/Count {pages}>>endobj\n".encode()
    objects.append(obj2)
    pos += len(obj2)

    # Object 3: Font
    offsets.append(pos)
    obj_font = b"3 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    objects.append(obj_font)
    pos += len(obj_font)

    # For each page: Page object + Content stream
    page_obj_num = 4
    for i in range(pages):
        page_text = f"{text} (page {i + 1})" if pages > 1 else text
        stream_content = (
            f"BT /F1 12 Tf 72 720 Td ({page_text}) Tj ET"
        ).encode()
        stream_len = len(stream_content)

        # Page object
        offsets.append(pos)
        page_obj = (
            f"{page_obj_num} 0 obj<</Type/Page/Parent 2 0 R"
            f"/MediaBox[0 0 612 792]"
            f"/Resources<</Font<</F1 3 0 R>>>>"
            f"/Contents {page_obj_num + 1} 0 R>>endobj\n"
        ).encode()
        objects.append(page_obj)
        pos += len(page_obj)

        # Content stream
        offsets.append(pos)
        stream_obj = (
            f"{page_obj_num + 1} 0 obj<</Length {stream_len}>>\n"
            f"stream\n"
        ).encode() + stream_content + b"\nendstream\nendobj\n"
        objects.append(stream_obj)
        pos += len(stream_obj)

        page_obj_num += 2

    # Cross-reference table
    xref_pos = pos
    total_objs = page_obj_num
    xref = f"xref\n0 {total_objs}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        xref += f"{offset:010d} 00000 n \n".encode()

    trailer = (
        f"trailer<</Size {total_objs}/Root 1 0 R>>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()

    path.write_bytes(header + b"".join(objects) + xref + trailer)


def create_scanned_pdf(path: Path) -> None:
    """Create a PDF with no text layer (simulates a scanned document).

    Uses image XObject reference instead of text operators so pdfplumber
    will find zero char objects on each page.
    """
    # Content stream with only an image Do operator (no text)
    stream_content = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    stream_len = len(stream_content)

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R"
        b"/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R>>endobj\n"
    )
    pdf += (
        f"4 0 obj<</Length {stream_len}>>\nstream\n"
    ).encode() + stream_content + b"\nendstream\nendobj\n"

    xref_pos = len(pdf)
    pdf += (
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000052 00000 n \n"
        b"0000000101 00000 n \n"
        b"0000000200 00000 n \n"
    )
    pdf += f"trailer<</Size 5/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF".encode()
    path.write_bytes(pdf)


def create_minimal_docx(
    path: Path,
    text: str = "Hello world",
    title: str = "",
    author: str = "",
) -> None:
    """Create a minimal DOCX with text and optional metadata."""
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    if title:
        doc.core_properties.title = title
    if author:
        doc.core_properties.author = author
    doc.save(str(path))


@pytest.fixture()
def tmp_corpus_with_documents(tmp_path: Path) -> Path:
    """Corpus with PDFs and DOCXes for text extraction testing."""
    # Native PDFs with text
    create_pdf_with_text(tmp_path / "report1.pdf", "First report content")
    create_pdf_with_text(tmp_path / "report2.pdf", "Second report with more text " * 20)
    create_pdf_with_text(
        tmp_path / "multipage.pdf", "Multi-page document", pages=3
    )

    # Scanned PDF (no text layer)
    create_scanned_pdf(tmp_path / "scanned.pdf")

    # DOCX files with metadata
    create_minimal_docx(
        tmp_path / "letter.docx",
        text="Dear Sir, This is a test letter.",
        title="Test Letter",
        author="John Doe",
    )
    create_minimal_docx(
        tmp_path / "memo.docx",
        text="Internal memo content here.",
        title="Memo",
    )

    # Plain text files (not extractable by text.py)
    (tmp_path / "readme.txt").write_text("Just a readme file.", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")

    return tmp_path


def create_pdf_with_pii(path: Path) -> None:
    """Create a PDF containing PII-like content for testing."""
    text = (
        "Contact: john.doe@example.com\n"
        "SSN: 123-45-6789\n"
        "Phone: (555) 123-4567\n"
        "CC: 4111 1111 1111 1111\n"
        "IP: 192.168.1.100\n"
        "Normal text without PII here."
    )
    create_pdf_with_text(path, text)


@pytest.fixture()
def tmp_corpus_with_pii(tmp_path: Path) -> Path:
    """Corpus with files containing PII-like content."""
    # PDF with PII
    create_pdf_with_pii(tmp_path / "pii_doc.pdf")
    # Clean PDF (no PII)
    create_pdf_with_text(tmp_path / "clean.pdf", "No sensitive data here at all.")
    # Text file with PII
    pii_txt = tmp_path / "contacts.txt"
    pii_txt.write_text(
        "Email: alice@test.org\nPhone: 555-987-6543\n",
        encoding="utf-8",
    )
    # CSV with PII-like content
    pii_csv = tmp_path / "data.csv"
    pii_csv.write_text(
        "name,email,ssn\nBob,bob@corp.io,987-65-4321\n",
        encoding="utf-8",
    )
    # Clean text file
    (tmp_path / "readme.txt").write_text("No PII here.", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def tmp_multilang_corpus(tmp_path: Path) -> Path:
    """Create a corpus with multi-language text content."""
    # English
    (tmp_path / "english.txt").write_text(
        "The quick brown fox jumps over the lazy dog. "
        "This is a simple English document for testing purposes. "
        "It contains enough words for the stop-word detection to work.",
        encoding="utf-8",
    )
    # Spanish
    (tmp_path / "spanish.txt").write_text(
        "El gato está en la mesa. Los perros son grandes y fuertes. "
        "Esta es una prueba del sistema de detección de idiomas para "
        "el proyecto que estamos desarrollando.",
        encoding="utf-8",
    )
    # French
    (tmp_path / "french.txt").write_text(
        "Le chat est sur la table. Les chiens sont grands et forts. "
        "Ceci est un test du système de détection de langue pour "
        "le projet que nous développons.",
        encoding="utf-8",
    )
    # German
    (tmp_path / "german.txt").write_text(
        "Der Hund ist auf dem Tisch. Die Katzen sind nicht im Haus. "
        "Das ist ein Test für das Spracherkennungssystem und "
        "die Erkennung von verschiedenen Sprachen.",
        encoding="utf-8",
    )
    # Latin-1 encoded German file
    (tmp_path / "latin1_german.txt").write_bytes(
        "Der Hund ist auf dem Tisch. Die Katzen sind nicht im Haus. "
        "Das ist ein Test für das Spracherkennungssystem und "
        "die Erkennung von verschiedenen Sprachen.".encode("iso-8859-1")
    )
    # PDF with English text
    create_pdf_with_text(
        tmp_path / "report.pdf",
        "This is an English report with enough text for detection.",
    )
    # DOCX with English text
    create_minimal_docx(
        tmp_path / "memo.docx",
        text="This is a memo document with English text for testing.",
    )
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
