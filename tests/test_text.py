"""Tests for text extraction pipeline."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.scanner import WalkResult
from field_check.scanner.inventory import InventoryResult, analyze_inventory
from field_check.scanner.sampling import select_sample
from field_check.scanner.text import TextExtractionResult, extract_text
from field_check.scanner.text_workers import _extract_docx, _extract_pdf
from tests.conftest import (
    create_minimal_docx,
    create_pdf_with_text,
    create_scanned_pdf,
)


def _walk_and_inventory(tmp_path: Path) -> tuple[WalkResult, InventoryResult]:
    """Walk a directory and analyze inventory."""
    from field_check.scanner import walk_directory

    config = FieldCheckConfig()
    walk = walk_directory(tmp_path, config)
    inv = analyze_inventory(walk)
    return walk, inv


def test_extract_pdf_native(tmp_path: Path) -> None:
    """Native PDF extracts text and has chars_per_page > 0."""
    pdf_path = tmp_path / "native.pdf"
    create_pdf_with_text(pdf_path, "Hello world test content")

    result = _extract_pdf(str(pdf_path))

    assert result.error is None
    assert result.page_count >= 1
    assert result.text_length > 0
    assert result.chars_per_page > 0
    assert not result.is_scanned
    assert not result.is_mixed_scan


def test_extract_pdf_scanned(tmp_path: Path) -> None:
    """Scanned PDF is detected with is_scanned=True."""
    pdf_path = tmp_path / "scanned.pdf"
    create_scanned_pdf(pdf_path)

    result = _extract_pdf(str(pdf_path))

    assert result.error is None
    assert result.is_scanned
    assert result.chars_per_page == 0.0
    assert result.classification == "image_heavy"


def test_extract_pdf_metadata(tmp_path: Path) -> None:
    """PDF metadata fields are extracted."""
    pdf_path = tmp_path / "meta.pdf"
    create_pdf_with_text(pdf_path, "Some content")

    result = _extract_pdf(str(pdf_path))

    assert result.error is None
    assert "title" in result.metadata
    assert "author" in result.metadata
    assert "creation_date" in result.metadata


def test_extract_docx_text(tmp_path: Path) -> None:
    """DOCX text extraction works."""
    docx_path = tmp_path / "test.docx"
    create_minimal_docx(docx_path, text="This is test content for DOCX")

    result = _extract_docx(str(docx_path))

    assert result.error is None
    assert result.text_length > 0
    assert result.text_length > 10
    assert result.classification == "text_heavy"


def test_extract_docx_metadata(tmp_path: Path) -> None:
    """DOCX metadata (title, author) is extracted."""
    docx_path = tmp_path / "meta.docx"
    create_minimal_docx(
        docx_path,
        text="Content here",
        title="My Title",
        author="Jane Doe",
    )

    result = _extract_docx(str(docx_path))

    assert result.error is None
    assert result.metadata.get("title") == "My Title"
    assert result.metadata.get("author") == "Jane Doe"


def test_extract_text_aggregate_counts(tmp_corpus_with_documents: Path) -> None:
    """Aggregate result counts match individual file processing."""
    walk, inv = _walk_and_inventory(tmp_corpus_with_documents)
    config = FieldCheckConfig(sampling_rate=1.0)
    sample = select_sample(walk, inv, config)

    result = extract_text(sample, inv, max_workers=1)

    assert isinstance(result, TextExtractionResult)
    # 4 PDFs + 2 DOCXes = 6 extractable files
    assert result.total_processed == 6
    # Scanned/native/mixed counts are PDF-only (4 PDFs)
    pdf_classified = result.scanned_count + result.native_count + result.mixed_scan_count
    assert pdf_classified == 4


def test_extract_text_scanned_detection(tmp_corpus_with_documents: Path) -> None:
    """Scanned PDFs are correctly detected in aggregate."""
    walk, inv = _walk_and_inventory(tmp_corpus_with_documents)
    config = FieldCheckConfig(sampling_rate=1.0)
    sample = select_sample(walk, inv, config)

    result = extract_text(sample, inv, max_workers=1)

    assert result.scanned_count >= 1  # At least the scanned.pdf


def test_extract_text_metadata_completeness(tmp_corpus_with_documents: Path) -> None:
    """Per-field metadata completeness is tallied."""
    walk, inv = _walk_and_inventory(tmp_corpus_with_documents)
    config = FieldCheckConfig(sampling_rate=1.0)
    sample = select_sample(walk, inv, config)

    result = extract_text(sample, inv, max_workers=1)

    assert result.metadata_total_checked > 0
    # letter.docx has title="Test Letter" and author="John Doe"
    assert result.metadata_field_counts.get("title", 0) >= 1
    assert result.metadata_field_counts.get("author", 0) >= 1


def test_extract_text_error_handling(tmp_path: Path) -> None:
    """Corrupt file produces error without crashing."""
    # Write garbage bytes to a .pdf file
    bad_pdf = tmp_path / "garbage.pdf"
    bad_pdf.write_bytes(b"this is not a pdf at all")

    result = _extract_pdf(str(bad_pdf))

    assert result.error is not None


def test_extract_text_empty_sample(tmp_path: Path) -> None:
    """No extractable files returns empty result."""
    # Create only text files (not extractable by text.py)
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")

    walk, inv = _walk_and_inventory(tmp_path)
    config = FieldCheckConfig(sampling_rate=1.0)
    sample = select_sample(walk, inv, config)

    result = extract_text(sample, inv, max_workers=1)

    assert result.total_processed == 0
    assert result.file_results == []


def test_extract_text_progress_callback(tmp_corpus_with_documents: Path) -> None:
    """Progress callback is called with correct counts."""
    walk, inv = _walk_and_inventory(tmp_corpus_with_documents)
    config = FieldCheckConfig(sampling_rate=1.0)
    sample = select_sample(walk, inv, config)

    progress_calls: list[tuple[int, int]] = []

    def on_progress(current: int, total: int) -> None:
        progress_calls.append((current, total))

    extract_text(sample, inv, max_workers=1, progress_callback=on_progress)

    assert len(progress_calls) > 0
    # Last call should have current == total
    last_current, last_total = progress_calls[-1]
    assert last_current == last_total


class TestFormatExtractors:
    """Tests for EML and EPUB text extraction (stdlib, no extra deps)."""

    def test_extract_eml(self, tmp_path: Path) -> None:
        """EML extraction should capture headers and body."""
        from field_check.scanner.text_workers import _extract_eml

        eml = tmp_path / "test.eml"
        eml.write_bytes(
            b"From: sender@example.com\r\n"
            b"To: recipient@example.com\r\n"
            b"Subject: Test Email\r\n"
            b"Date: Wed, 01 Jan 2025 12:00:00 +0000\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Hello, this is a test email body.\r\n"
        )
        result = _extract_eml(str(eml))
        assert result.error is None
        assert "Test Email" in result.text
        assert "Hello" in result.text
        assert result.metadata["title"] == "Test Email"
        assert result.metadata["author"] == "sender@example.com"

    def test_extract_epub(self, tmp_path: Path) -> None:
        """EPUB extraction should parse XHTML content."""
        import zipfile

        from field_check.scanner.text_workers import _extract_epub

        epub = tmp_path / "test.epub"
        with zipfile.ZipFile(epub, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr(
                "OEBPS/chapter1.xhtml",
                "<html><body><p>Chapter one text here.</p></body></html>",
            )
        result = _extract_epub(str(epub))
        assert result.error is None
        assert "Chapter one text here." in result.text

    def test_extract_eml_malformed(self, tmp_path: Path) -> None:
        """Malformed EML should not crash."""
        from field_check.scanner.text_workers import _extract_eml

        eml = tmp_path / "bad.eml"
        eml.write_bytes(b"This is not a valid email at all\x00\xff\xfe")
        result = _extract_eml(str(eml))
        # Should not crash — may have text or error
        assert isinstance(result.text, str)

    def test_extract_epub_no_html(self, tmp_path: Path) -> None:
        """EPUB with no HTML files should return empty text."""
        import zipfile

        from field_check.scanner.text_workers import _extract_epub

        epub = tmp_path / "empty.epub"
        with zipfile.ZipFile(epub, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("META-INF/container.xml", "<container/>")
        result = _extract_epub(str(epub))
        assert result.error is None
        assert result.text == ""
