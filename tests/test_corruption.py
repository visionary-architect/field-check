"""Tests for the corruption detection scanner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from field_check.config import FieldCheckConfig
from field_check.scanner import WalkResult, walk_directory
from field_check.scanner.corruption import check_corruption
from tests.conftest import (
    create_corrupt_pdf,
    create_encrypted_pdf,
    create_encrypted_zip,
    create_minimal_pdf,
    create_minimal_png,
    create_minimal_zip,
)


def _walk(path: Path) -> WalkResult:
    """Helper to walk a directory with default config."""
    return walk_directory(path, FieldCheckConfig())


def test_check_empty_file(tmp_path: Path) -> None:
    """0-byte file should be flagged as empty."""
    (tmp_path / "empty.dat").write_bytes(b"")
    result = check_corruption(_walk(tmp_path))
    assert result.empty_count == 1
    flagged = [f for f in result.flagged_files if f.status == "empty"]
    assert len(flagged) == 1


def test_check_near_empty_file(tmp_path: Path) -> None:
    """Small file (10 bytes) should be flagged as near_empty."""
    (tmp_path / "tiny.dat").write_bytes(b"0123456789")
    result = check_corruption(_walk(tmp_path))
    assert result.near_empty_count == 1
    flagged = [f for f in result.flagged_files if f.status == "near_empty"]
    assert len(flagged) == 1


def test_check_valid_pdf(tmp_path: Path) -> None:
    """Valid PDF should be status ok."""
    create_minimal_pdf(tmp_path / "valid.pdf")
    result = check_corruption(_walk(tmp_path))
    assert result.ok_count == 1
    assert result.corrupt_count == 0


def test_check_valid_png(tmp_path: Path) -> None:
    """Valid PNG should be status ok."""
    create_minimal_png(tmp_path / "valid.png")
    result = check_corruption(_walk(tmp_path))
    assert result.ok_count == 1
    assert result.corrupt_count == 0


def test_check_corrupt_pdf(tmp_path: Path) -> None:
    """PNG header in .pdf file — filetype sees PNG (no MIME mismatch)."""
    create_corrupt_pdf(tmp_path / "bad.pdf")
    result = check_corruption(_walk(tmp_path))
    # filetype detects by magic bytes (PNG), so detected MIME matches header.
    # This is not a corruption case — it's a misnamed file.
    assert result.total_checked == 1
    assert result.corrupt_count == 0


def test_check_corrupt_pdf_via_mock(tmp_path: Path) -> None:
    """File with non-PDF content but detected as PDF should be flagged corrupt."""
    bad_file = tmp_path / "bad.dat"
    bad_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    walk = _walk(tmp_path)
    with patch(
        "field_check.scanner.corruption._detect_mime",
        return_value="application/pdf",
    ):
        result = check_corruption(walk)

    assert result.corrupt_count == 1
    flagged = [f for f in result.flagged_files if f.status == "corrupt"]
    assert len(flagged) == 1


def test_check_corrupt_magic_mismatch(tmp_path: Path) -> None:
    """File where detected MIME doesn't match header should be corrupt."""
    bad_file = tmp_path / "mismatch.dat"
    # Write random bytes (no valid magic)
    bad_file.write_bytes(b"NOTAPDF\x00" * 20)

    walk = _walk(tmp_path)
    # Mock filetype to return application/pdf for this file
    with patch(
        "field_check.scanner.corruption._detect_mime",
        return_value="application/pdf",
    ):
        result = check_corruption(walk)

    assert result.corrupt_count == 1
    flagged = [f for f in result.flagged_files if f.status == "corrupt"]
    assert len(flagged) == 1


def test_check_encrypted_pdf(tmp_path: Path) -> None:
    """PDF with /Encrypt should be flagged as encrypted_pdf."""
    create_encrypted_pdf(tmp_path / "enc.pdf")
    result = check_corruption(_walk(tmp_path))
    assert result.encrypted_count == 1
    flagged = [f for f in result.flagged_files if f.status == "encrypted_pdf"]
    assert len(flagged) == 1


def test_check_encrypted_zip(tmp_path: Path) -> None:
    """ZIP with encryption flag should be flagged as encrypted_zip."""
    create_encrypted_zip(tmp_path / "enc.zip")
    result = check_corruption(_walk(tmp_path))
    assert result.encrypted_count == 1
    flagged = [f for f in result.flagged_files if f.status == "encrypted_zip"]
    assert len(flagged) == 1


def test_check_normal_zip(tmp_path: Path) -> None:
    """Valid non-encrypted ZIP should be status ok."""
    create_minimal_zip(tmp_path / "normal.zip")
    result = check_corruption(_walk(tmp_path))
    assert result.ok_count == 1
    assert result.encrypted_count == 0


def test_corruption_result_counts(tmp_corpus_with_issues: Path) -> None:
    """All counts should match the known test corpus."""
    result = check_corruption(_walk(tmp_corpus_with_issues))
    assert result.total_checked == 7
    assert result.empty_count == 1
    assert result.near_empty_count == 1
    assert result.encrypted_count >= 1  # at least encrypted PDF or ZIP
    # ok includes valid PDF and valid PNG (plus corrupt.pdf detected as PNG)
    assert result.ok_count >= 1


def test_only_flagged_in_results(tmp_path: Path) -> None:
    """OK files should NOT appear in flagged_files."""
    create_minimal_pdf(tmp_path / "good.pdf")
    create_minimal_png(tmp_path / "good.png")
    (tmp_path / "empty.dat").write_bytes(b"")

    result = check_corruption(_walk(tmp_path))
    # Only the empty file should be flagged
    assert len(result.flagged_files) == 1
    assert result.flagged_files[0].status == "empty"


def test_check_corruption_empty_walk() -> None:
    """Empty WalkResult should return zeroed CorruptionResult."""
    result = check_corruption(WalkResult())
    assert result.total_checked == 0
    assert result.ok_count == 0
    assert result.flagged_files == []


def test_check_corruption_progress_callback(tmp_path: Path) -> None:
    """Progress callback should be called once per file."""
    create_minimal_pdf(tmp_path / "a.pdf")
    (tmp_path / "b.txt").write_text("hello", encoding="utf-8")

    calls: list[tuple[int, int]] = []

    def callback(current: int, total: int) -> None:
        calls.append((current, total))

    walk = _walk(tmp_path)
    check_corruption(walk, progress_callback=callback)

    assert len(calls) == len(walk.files)
    assert calls[-1][0] == calls[-1][1]


def test_unreadable_file(tmp_path: Path) -> None:
    """File that raises OSError on read should be unreadable."""
    target = tmp_path / "locked.dat"
    target.write_bytes(b"some content that is big enough" * 10)

    walk = _walk(tmp_path)
    # Mock open to raise OSError for this file
    original_open = open

    def mock_open(path, *args, **kwargs):
        if str(path) == str(target):
            raise PermissionError("Access denied")
        return original_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        result = check_corruption(walk)

    assert result.unreadable_count == 1
    flagged = [f for f in result.flagged_files if f.status == "unreadable"]
    assert len(flagged) == 1


def test_file_types_skips_filetype_guess(tmp_path: Path) -> None:
    """Passing file_types should use pre-computed MIME, skipping filetype.guess."""
    create_minimal_pdf(tmp_path / "a.pdf")
    create_minimal_png(tmp_path / "b.png")

    walk = _walk(tmp_path)
    # Build file_types dict with known MIME types
    file_types = {entry.path: "application/pdf" for entry in walk.files}

    with patch(
        "field_check.scanner.corruption._detect_mime",
    ) as mock_detect:
        result = check_corruption(walk, file_types=file_types)
        # _detect_mime should NOT be called since we provided file_types
        mock_detect.assert_not_called()

    assert result.total_checked == len(walk.files)
    # PNG file was told it's PDF — magic mismatch should flag it as corrupt
    assert result.corrupt_count == 1


class TestOfficeEncryption:
    """Tests for Office file (OOXML) encryption detection."""

    def test_encrypted_office_detected(self, tmp_path: Path) -> None:
        """OOXML file detected as encrypted should be flagged."""
        import zipfile

        docx = tmp_path / "encrypted.docx"
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("word/document.xml", "<document/>")

        walk = _walk(tmp_path)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        file_types = {walk.files[0].path: mime}

        with patch(
            "field_check.scanner.corruption._check_encrypted_office",
            return_value=True,
        ):
            result = check_corruption(walk, file_types=file_types)

        assert result.encrypted_count == 1
        flagged = [f for f in result.flagged_files if f.status == "encrypted_office"]
        assert len(flagged) == 1

    def test_unencrypted_office_passes(self, tmp_path: Path) -> None:
        """Non-encrypted OOXML file should pass."""
        import zipfile

        docx = tmp_path / "normal.docx"
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("word/document.xml", "<document/>")

        walk = _walk(tmp_path)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        file_types = {walk.files[0].path: mime}

        with patch(
            "field_check.scanner.corruption._check_encrypted_office",
            return_value=False,
        ):
            result = check_corruption(walk, file_types=file_types)

        assert result.encrypted_count == 0
        assert result.ok_count == 1

    def test_graceful_without_msoffcrypto(self, tmp_path: Path) -> None:
        """Without msoffcrypto-tool, detection should return False."""
        import zipfile

        from field_check.scanner.corruption import _check_encrypted_office

        docx = tmp_path / "test.docx"
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")

        with patch.dict("sys.modules", {"msoffcrypto": None}):
            assert _check_encrypted_office(docx) is False


class TestTruncationDetection:
    """Tests for PDF, DOCX, and image truncation detection."""

    def test_truncated_pdf_missing_eof(self, tmp_path: Path) -> None:
        """PDF without %%EOF marker should be flagged as truncated."""
        pdf = tmp_path / "trunc.pdf"
        # Valid header but no %%EOF (>50 bytes to avoid near-empty)
        pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n" + b"\x00" * 100)

        walk = _walk(tmp_path)
        file_types = {walk.files[0].path: "application/pdf"}
        result = check_corruption(walk, file_types=file_types)
        assert result.truncated_count == 1
        flagged = [f for f in result.flagged_files if f.status == "truncated"]
        assert len(flagged) == 1
        assert "%%EOF" in flagged[0].detail

    def test_valid_pdf_has_eof(self, tmp_path: Path) -> None:
        """PDF with %%EOF marker should pass."""
        pdf = tmp_path / "valid.pdf"
        pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n%%EOF\n")

        walk = _walk(tmp_path)
        file_types = {walk.files[0].path: "application/pdf"}
        result = check_corruption(walk, file_types=file_types)
        assert result.truncated_count == 0

    def test_corrupt_docx_bad_zip(self, tmp_path: Path) -> None:
        """DOCX with invalid ZIP structure should be flagged."""
        docx = tmp_path / "bad.docx"
        # Valid PK header but garbage after
        docx.write_bytes(b"PK\x03\x04" + b"\x00" * 100)

        walk = _walk(tmp_path)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        file_types = {walk.files[0].path: mime}
        result = check_corruption(walk, file_types=file_types)
        assert result.corrupt_count == 1

    def test_docx_missing_content_types(self, tmp_path: Path) -> None:
        """DOCX missing [Content_Types].xml should be flagged."""
        import zipfile

        docx = tmp_path / "missing_ct.docx"
        with zipfile.ZipFile(docx, "w") as zf:
            zf.writestr("word/document.xml", "<document/>")

        walk = _walk(tmp_path)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        file_types = {walk.files[0].path: mime}
        result = check_corruption(walk, file_types=file_types)
        assert result.corrupt_count == 1

    def test_truncated_jpeg_missing_eoi(self, tmp_path: Path) -> None:
        """JPEG without EOI marker should be flagged as truncated."""
        jpg = tmp_path / "trunc.jpg"
        # Valid JPEG header but no EOI (0xFF 0xD9)
        jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        walk = _walk(tmp_path)
        file_types = {walk.files[0].path: "image/jpeg"}
        result = check_corruption(walk, file_types=file_types)
        assert result.truncated_count == 1

    def test_valid_jpeg_has_eoi(self, tmp_path: Path) -> None:
        """JPEG with EOI marker should pass."""
        jpg = tmp_path / "valid.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9")

        walk = _walk(tmp_path)
        file_types = {walk.files[0].path: "image/jpeg"}
        result = check_corruption(walk, file_types=file_types)
        assert result.truncated_count == 0

    def test_truncated_png_missing_iend(self, tmp_path: Path) -> None:
        """PNG without IEND chunk should be flagged as truncated."""
        png = tmp_path / "trunc.png"
        # Valid PNG header but no IEND
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        walk = _walk(tmp_path)
        file_types = {walk.files[0].path: "image/png"}
        result = check_corruption(walk, file_types=file_types)
        assert result.truncated_count == 1
