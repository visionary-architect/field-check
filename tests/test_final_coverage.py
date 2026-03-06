"""Final coverage tests targeting remaining uncovered lines across modules."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from field_check.cli import main
from field_check.config import FieldCheckConfig
from field_check.report import determine_exit_code
from field_check.scanner import FileEntry, WalkResult, walk_directory
from field_check.scanner.corruption import CorruptionResult
from field_check.scanner.dedup import DedupResult
from field_check.scanner.inventory import (
    AgeDistribution,
    DirectoryStructure,
    InventoryResult,
    SizeDistribution,
)
from field_check.scanner.language import detect_language
from field_check.scanner.pii import (
    PIIScanResult,
    _extract_text_for_pii,
    scan_pii,
)
from field_check.scanner.sampling import SampleResult
from field_check.scanner.text import (
    CHARS_PER_PAGE_IMAGE_HEAVY,
    CHARS_PER_PAGE_TEXT_HEAVY,
    TEXT_SIZE_RATIO_IMAGE_HEAVY,
    _extract_pdf,
    _page_count_bucket,
    build_text_cache,
)

ROOT = Path("/corpus")

# Saved reference to real os.stat before any tests patch it
_real_os_stat = os.stat


def _entry(name: str, size: int = 100) -> FileEntry:
    """Create a FileEntry rooted under /corpus."""
    return FileEntry(
        path=ROOT / name,
        relative_path=Path(name),
        size=size,
        mtime=1.7e9,
        ctime=1.7e9,
        is_symlink=False,
    )


def _inventory(files: list[FileEntry], types: dict) -> InventoryResult:
    return InventoryResult(
        total_files=len(files),
        total_size=sum(f.size for f in files),
        file_types=types,
        size_distribution=SizeDistribution(),
        age_distribution=AgeDistribution(),
        dir_structure=DirectoryStructure(total_dirs=1),
    )


def _sample(files: list[FileEntry]) -> SampleResult:
    return SampleResult(
        selected_files=files,
        total_sample_size=len(files),
        total_population_size=len(files),
        sampling_rate=1.0,
        is_census=True,
    )


def _mock_pdfplumber_open(mock_pdf):
    """Return a patch for pdfplumber.open that works with local imports."""
    return patch.dict(
        "sys.modules",
        {"pdfplumber": MagicMock(open=MagicMock(return_value=mock_pdf))},
    )


def _make_stat_wrapper(mock_fn):
    """Create an os.stat wrapper that delegates to real stat for Path objects.

    Path.exists(), Path.is_dir(), and Path.resolve() call os.stat(Path_obj).
    The walker code calls os.stat(string_path). We use the argument type
    to distinguish: Path -> real stat, str -> mock function.
    """

    def wrapper(path, *args, **kwargs):
        if isinstance(path, Path):
            return _real_os_stat(path, *args, **kwargs)
        return mock_fn(path, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# cli.py -- Lines 101-103: KeyboardInterrupt during walk_directory
# ---------------------------------------------------------------------------


class TestCLIKeyboardInterrupt:
    def test_keyboard_interrupt_during_scan(self, tmp_path):
        """cli.py lines 101-103: KeyboardInterrupt prints message and exits 2."""
        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        with patch(
            "field_check.cli.walk_directory",
            side_effect=KeyboardInterrupt,
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["scan", str(tmp_path)])
            assert result.exit_code == 2
            assert "Scan interrupted" in result.output


# ---------------------------------------------------------------------------
# cli.py -- Lines 254-255: ValueError from generate_report
# ---------------------------------------------------------------------------


class TestCLIValueErrorFromReport:
    def test_generate_report_value_error(self, tmp_path):
        """cli.py lines 254-255: ValueError from generate_report -> UsageError."""
        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        with patch(
            "field_check.cli.generate_report",
            side_effect=ValueError("bad format"),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["scan", str(tmp_path)])
            assert result.exit_code != 0
            assert "bad format" in result.output


# ---------------------------------------------------------------------------
# cli.py -- Line 266: sys.exit(exit_code) when exit_code != 0
# ---------------------------------------------------------------------------


class TestCLIExitCode:
    def test_nonzero_exit_code_from_thresholds(self, tmp_path):
        """cli.py line 266: sys.exit(exit_code) when threshold exceeded."""
        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        with patch(
            "field_check.cli.determine_exit_code",
            return_value=(1, ["Duplicate rate 15.0% >= threshold 10.0%"]),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["scan", str(tmp_path)])
            assert result.exit_code == 1


# ---------------------------------------------------------------------------
# text.py -- Line 57: _page_count_bucket fallback ">500 pages"
# ---------------------------------------------------------------------------


class TestPageCountBucketFallback:
    def test_negative_page_count_fallback(self):
        """text.py line 57: fallback return for unmatched page counts."""
        assert _page_count_bucket(-1) == ">500 pages"

    def test_zero_page_count_fallback(self):
        """text.py line 57: 0 does not match any bucket (low starts at 1)."""
        assert _page_count_bucket(0) == ">500 pages"


# ---------------------------------------------------------------------------
# text.py -- Line 145: is_mixed_scan = True (scanned + native pages)
# ---------------------------------------------------------------------------


class TestMixedScanPDF:
    def test_mixed_scan_pdf(self, tmp_path):
        """text.py line 145: PDF with both scanned and native pages."""
        from tests.conftest import create_pdf_with_text

        pdf_path = tmp_path / "mixed.pdf"
        create_pdf_with_text(pdf_path, "Some text content", pages=2)

        mock_page_native = MagicMock()
        mock_page_native.chars = [{"c": "a"}] * 50
        mock_page_native.extract_text.return_value = "Some text " * 50

        mock_page_scanned = MagicMock()
        mock_page_scanned.chars = []
        mock_page_scanned.extract_text.return_value = ""

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page_native, mock_page_scanned]
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with _mock_pdfplumber_open(mock_pdf):
            result = _extract_pdf(str(pdf_path))

        assert result.is_mixed_scan is True
        assert result.is_scanned is False


# ---------------------------------------------------------------------------
# text.py -- Lines 159-166: classification mixed zone
# ---------------------------------------------------------------------------


class TestPDFClassificationMixedZone:
    def test_mixed_zone_image_heavy_by_ratio(self, tmp_path):
        """text.py lines 161-164: mixed zone + low ratio -> image_heavy."""
        pdf_path = tmp_path / "mixed_ratio.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mid_chars = (CHARS_PER_PAGE_IMAGE_HEAVY + CHARS_PER_PAGE_TEXT_HEAVY) // 2
        low_ratio_text_bytes = 1

        mock_page = MagicMock()
        mock_page.chars = [{"c": "x"}] * mid_chars
        mock_page.extract_text.return_value = "x" * low_ratio_text_bytes

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        large_file_size = low_ratio_text_bytes * 1000

        with (
            _mock_pdfplumber_open(mock_pdf),
            patch("os.path.getsize", return_value=large_file_size),
        ):
            result = _extract_pdf(str(pdf_path))

        assert result.classification == "image_heavy"
        assert CHARS_PER_PAGE_IMAGE_HEAVY <= result.chars_per_page <= CHARS_PER_PAGE_TEXT_HEAVY

    def test_mixed_zone_mixed_by_ratio(self, tmp_path):
        """text.py lines 165-166: mixed zone + high ratio -> mixed."""
        pdf_path = tmp_path / "mixed_high.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        mid_chars = (CHARS_PER_PAGE_IMAGE_HEAVY + CHARS_PER_PAGE_TEXT_HEAVY) // 2
        large_text = "x" * 500

        mock_page = MagicMock()
        mock_page.chars = [{"c": "x"}] * mid_chars
        mock_page.extract_text.return_value = large_text

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        text_bytes = len(large_text.encode("utf-8"))
        file_size = int(text_bytes / (TEXT_SIZE_RATIO_IMAGE_HEAVY + 0.01))

        with (
            _mock_pdfplumber_open(mock_pdf),
            patch("os.path.getsize", return_value=file_size),
        ):
            result = _extract_pdf(str(pdf_path))

        assert result.classification == "mixed"


# ---------------------------------------------------------------------------
# text.py -- Line 403: charset_normalizer result is falsy
# ---------------------------------------------------------------------------


class TestTextCacheFalsyCharset:
    def test_cache_plain_text_charset_falsy(self, tmp_path):
        """text.py line 403: charset_normalizer returns falsy -> raw decode."""
        from field_check.scanner.text import _extract_text_for_cache

        p = tmp_path / "binary.txt"
        p.write_bytes(b"\x80\x81\x82\x83" * 10)

        mock_from_bytes = MagicMock()
        mock_best = MagicMock()
        mock_best.best.return_value = None
        mock_from_bytes.return_value = mock_best

        with patch.dict(
            "sys.modules",
            {"charset_normalizer": MagicMock(from_bytes=mock_from_bytes)},
        ):
            _text, enc, conf, err = _extract_text_for_cache(str(p), "text/plain")

        assert err is None
        assert enc == "utf-8"
        assert conf == 0.0


# ---------------------------------------------------------------------------
# text.py -- Lines 471, 477: progress_callback in error handlers
# ---------------------------------------------------------------------------


class TestBuildTextCacheProgressCallbacks:
    def test_timeout_with_progress_callback(self):
        """text.py line 471: progress_callback in TimeoutError handler."""
        f = [_entry("a.txt")]
        inv = _inventory(f, {ROOT / "a.txt": "text/plain"})

        callback = MagicMock()
        fut = MagicMock()
        fut.result.side_effect = TimeoutError()

        with (
            patch("field_check.scanner.text.ProcessPoolExecutor") as pool_cls,
            patch(
                "field_check.scanner.text.as_completed",
                return_value=iter([fut]),
            ),
        ):
            pool = MagicMock()
            pool_cls.return_value.__enter__ = MagicMock(return_value=pool)
            pool_cls.return_value.__exit__ = MagicMock(return_value=False)
            pool.submit.return_value = fut

            r = build_text_cache(
                _sample(f),
                inv,
                max_workers=1,
                progress_callback=callback,
            )

        assert r.extraction_errors == 1
        callback.assert_called()

    def test_exception_with_progress_callback(self):
        """text.py line 477: progress_callback in Exception handler."""
        f = [_entry("a.txt")]
        inv = _inventory(f, {ROOT / "a.txt": "text/plain"})

        callback = MagicMock()
        fut = MagicMock()
        fut.result.side_effect = RuntimeError("boom")

        with (
            patch("field_check.scanner.text.ProcessPoolExecutor") as pool_cls,
            patch(
                "field_check.scanner.text.as_completed",
                return_value=iter([fut]),
            ),
        ):
            pool = MagicMock()
            pool_cls.return_value.__enter__ = MagicMock(return_value=pool)
            pool_cls.return_value.__exit__ = MagicMock(return_value=False)
            pool.submit.return_value = fut

            r = build_text_cache(
                _sample(f),
                inv,
                max_workers=1,
                progress_callback=callback,
            )

        assert r.extraction_errors == 1
        callback.assert_called()


# ---------------------------------------------------------------------------
# pii.py -- Lines 152-155: _extract_text_for_pii PDF branch
# ---------------------------------------------------------------------------


class TestPIIExtractTextPDF:
    def test_extract_text_for_pii_pdf(self, tmp_path):
        """pii.py lines 152-155: PDF extraction branch."""
        from tests.conftest import create_pdf_with_text

        pdf_path = tmp_path / "test.pdf"
        create_pdf_with_text(pdf_path, "Hello from PDF for PII test")
        text = _extract_text_for_pii(str(pdf_path), "application/pdf")
        assert "Hello from PDF" in text


# ---------------------------------------------------------------------------
# pii.py -- Lines 160-163: _extract_text_for_pii DOCX branch
# ---------------------------------------------------------------------------


class TestPIIExtractTextDOCX:
    def test_extract_text_for_pii_docx(self, tmp_path):
        """pii.py lines 160-163: DOCX extraction branch."""
        from tests.conftest import create_minimal_docx

        docx_path = tmp_path / "test.docx"
        create_minimal_docx(docx_path, text="Hello from DOCX for PII test")
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        text = _extract_text_for_pii(str(docx_path), mime)
        assert "Hello from DOCX" in text


# ---------------------------------------------------------------------------
# pii.py -- Line 334: early return when no extractable files
# ---------------------------------------------------------------------------


class TestPIIScanNoExtractableFiles:
    def test_scan_pii_no_extractable(self):
        """pii.py line 334: early return when no files have extractable MIME."""
        f = [_entry("image.png")]
        inv = _inventory(f, {ROOT / "image.png": "image/png"})
        config = FieldCheckConfig()
        result = scan_pii(_sample(f), inv, config)
        assert result.total_scanned == 0


# ---------------------------------------------------------------------------
# scanner/__init__.py -- Lines 103-106: symlink loop via dev_ino revisit
# ---------------------------------------------------------------------------


class TestWalkerSymlinkLoopDevIno:
    def test_dir_symlink_loop_via_dev_ino(self, tmp_path):
        """scanner/__init__.py lines 103-106: inode-based loop detection."""
        config = FieldCheckConfig(exclude=[])

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.txt").write_text("content", encoding="utf-8")
        (tmp_path / "a.txt").write_text("hi", encoding="utf-8")

        first_stat = _real_os_stat(str(tmp_path))

        walk_items = [
            (str(tmp_path), ["sub"], ["a.txt"]),
            (str(sub), [], ["file.txt"]),
        ]

        def mock_stat_fn(path, *args, **kwargs):
            """Return same dev/ino for sub as for root."""
            if str(sub) in str(path):
                return first_stat
            return _real_os_stat(path)

        file_lstat = MagicMock()
        file_lstat.st_mode = stat.S_IFREG | 0o644
        file_lstat.st_size = 2
        file_lstat.st_mtime = 1.7e9
        file_lstat.st_ctime = 1.7e9
        file_lstat.st_ino = 12345

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch("field_check.scanner.os.lstat", return_value=file_lstat),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.symlink_loops) >= 1


# ---------------------------------------------------------------------------
# scanner/__init__.py -- Lines 110-115: Windows fallback (st_ino == 0)
# ---------------------------------------------------------------------------


class TestWalkerWindowsFallback:
    def test_windows_ino_zero_fallback(self, tmp_path):
        """scanner/__init__.py lines 110-115: st_ino == 0 uses resolved path."""
        config = FieldCheckConfig(exclude=[])
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")

        walk_items = [
            (str(tmp_path), [], ["file.txt"]),
        ]

        mock_dir_stat = MagicMock()
        mock_dir_stat.st_dev = 1
        mock_dir_stat.st_ino = 0

        file_lstat = MagicMock()
        file_lstat.st_mode = stat.S_IFREG | 0o644
        file_lstat.st_size = 7
        file_lstat.st_mtime = 1.7e9
        file_lstat.st_ctime = 1.7e9

        def mock_stat_fn(path, *args, **kwargs):
            return mock_dir_stat

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch("field_check.scanner.os.lstat", return_value=file_lstat),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.files) == 1

    def test_windows_ino_zero_revisit_loop(self, tmp_path):
        """scanner/__init__.py lines 112-114: revisited resolved path."""
        config = FieldCheckConfig(exclude=[])

        sub = tmp_path / "sub"
        sub.mkdir()

        walk_items = [
            (str(tmp_path), ["sub"], []),
            (str(sub), [], []),
        ]

        mock_dir_stat = MagicMock()
        mock_dir_stat.st_dev = 1
        mock_dir_stat.st_ino = 0

        def mock_stat_fn(path, *args, **kwargs):
            return mock_dir_stat

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch.object(Path, "resolve", return_value=tmp_path),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.symlink_loops) >= 1


# ---------------------------------------------------------------------------
# scanner/__init__.py -- Lines 120-123: OSError when stating directory
# ---------------------------------------------------------------------------


class TestWalkerDirOSError:
    def test_oserror_stating_directory(self, tmp_path):
        """scanner/__init__.py lines 120-123: OSError on os.stat for dir."""
        config = FieldCheckConfig(exclude=[])

        walk_items = [
            (str(tmp_path), ["bad"], []),
            (str(tmp_path / "bad"), [], ["file.txt"]),
        ]

        call_count = [0]

        def mock_stat_fn(path, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _real_os_stat(str(tmp_path))
            raise OSError("disk error")

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.files) == 0


# ---------------------------------------------------------------------------
# scanner/__init__.py -- Lines 135-151: Symlink subdirectory loop detection
# ---------------------------------------------------------------------------


class TestWalkerSubdirSymlinkLoop:
    def test_symlink_subdir_to_ancestor(self, tmp_path):
        """scanner/__init__.py lines 138-140: symlink to ancestor."""
        config = FieldCheckConfig(exclude=[])

        sub = tmp_path / "sub"
        sub.mkdir()

        walk_items = [
            (str(tmp_path), ["sub"], []),
        ]

        root_stat = MagicMock()
        root_stat.st_dev = 1
        root_stat.st_ino = 100

        def mock_stat_fn(path, *args, **kwargs):
            return root_stat

        original_is_symlink = Path.is_symlink
        saved_resolve = Path.resolve

        def fake_is_symlink(self):
            if self.name == "sub":
                return True
            return original_is_symlink(self)

        def fake_resolve(self):
            if self.name == "sub":
                return tmp_path
            return saved_resolve(self)

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch.object(Path, "is_symlink", fake_is_symlink),
            patch.object(Path, "resolve", fake_resolve),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.symlink_loops) >= 1

    def test_symlink_subdir_to_visited(self, tmp_path):
        """scanner/__init__.py lines 141-149: symlink to visited path."""
        config = FieldCheckConfig(exclude=[])

        sub = tmp_path / "link_sub"
        sub.mkdir()

        target = tmp_path / "already_visited"
        target.mkdir()

        walk_items = [
            (str(tmp_path), ["link_sub"], []),
        ]

        root_stat = MagicMock()
        root_stat.st_dev = 1
        root_stat.st_ino = 100

        def mock_stat_fn(path, *args, **kwargs):
            return root_stat

        saved_resolve = Path.resolve
        original_is_symlink = Path.is_symlink

        def fake_is_symlink(self):
            if self.name == "link_sub":
                return True
            return original_is_symlink(self)

        def fake_resolve(self):
            if self.name == "link_sub":
                return target
            return saved_resolve(self)

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch.object(Path, "is_symlink", fake_is_symlink),
            patch.object(Path, "resolve", fake_resolve),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.symlink_loops) >= 1


# ---------------------------------------------------------------------------
# scanner/__init__.py -- Line 172: skip special files
# ---------------------------------------------------------------------------


class TestWalkerSkipSpecialFiles:
    def test_skip_special_file(self, tmp_path):
        """scanner/__init__.py line 172: skip non-regular, non-symlink."""
        config = FieldCheckConfig(exclude=[])
        (tmp_path / "normal.txt").write_text("hi", encoding="utf-8")

        walk_items = [
            (str(tmp_path), [], ["normal.txt", "pipe_file"]),
        ]

        real_root_stat = _real_os_stat(str(tmp_path))

        normal_lstat = MagicMock()
        normal_lstat.st_mode = stat.S_IFREG | 0o644
        normal_lstat.st_size = 2
        normal_lstat.st_mtime = 1.7e9
        normal_lstat.st_ctime = 1.7e9

        pipe_lstat = MagicMock()
        pipe_lstat.st_mode = stat.S_IFIFO | 0o644

        def lstat_side(path, *args, **kwargs):
            if "pipe_file" in str(path):
                return pipe_lstat
            return normal_lstat

        def mock_stat_fn(path, *args, **kwargs):
            return real_root_stat

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch("field_check.scanner.os.lstat", side_effect=lstat_side),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.files) == 1


# ---------------------------------------------------------------------------
# scanner/__init__.py -- Lines 177-183: Symlink file handling
# ---------------------------------------------------------------------------


class TestWalkerSymlinkFileHandling:
    def test_symlink_to_regular_file(self, tmp_path):
        """scanner/__init__.py lines 175-185: symlink to regular file."""
        config = FieldCheckConfig(exclude=[])

        walk_items = [
            (str(tmp_path), [], ["link.txt"]),
        ]

        real_root_stat = _real_os_stat(str(tmp_path))

        link_lstat = MagicMock()
        link_lstat.st_mode = stat.S_IFLNK | 0o777

        target_fstat = MagicMock()
        target_fstat.st_mode = stat.S_IFREG | 0o644
        target_fstat.st_size = 42
        target_fstat.st_mtime = 1.7e9
        target_fstat.st_ctime = 1.7e9

        call_count = [0]

        def mock_stat_fn(path, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return real_root_stat
            return target_fstat

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch("field_check.scanner.os.lstat", return_value=link_lstat),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.files) == 1
        assert result.files[0].is_symlink is True

    def test_symlink_to_non_regular(self, tmp_path):
        """scanner/__init__.py lines 179-180: symlink to non-regular."""
        config = FieldCheckConfig(exclude=[])

        walk_items = [
            (str(tmp_path), [], ["link_to_dir"]),
        ]

        real_root_stat = _real_os_stat(str(tmp_path))

        link_lstat = MagicMock()
        link_lstat.st_mode = stat.S_IFLNK | 0o777

        dir_target_stat = MagicMock()
        dir_target_stat.st_mode = stat.S_IFDIR | 0o755

        call_count = [0]

        def mock_stat_fn(path, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return real_root_stat
            return dir_target_stat

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch("field_check.scanner.os.lstat", return_value=link_lstat),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.files) == 0

    def test_broken_symlink(self, tmp_path):
        """scanner/__init__.py lines 181-183: broken symlink -> skip."""
        config = FieldCheckConfig(exclude=[])

        walk_items = [
            (str(tmp_path), [], ["broken_link"]),
        ]

        real_root_stat = _real_os_stat(str(tmp_path))

        link_lstat = MagicMock()
        link_lstat.st_mode = stat.S_IFLNK | 0o777

        call_count = [0]

        def mock_stat_fn(path, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return real_root_stat
            raise OSError("broken symlink")

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch("field_check.scanner.os.lstat", return_value=link_lstat),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.files) == 0


# ---------------------------------------------------------------------------
# language.py -- Line 213: unreachable "Unknown" guard
# ---------------------------------------------------------------------------


class TestLanguageUnreachableGuard:
    def test_total_classified_zero_with_script_dist(self):
        """language.py line 213: total_classified == 0 with truthy script_dist.

        Logically unreachable since truthy dict means sum > 0. We mock
        _get_script_distribution to return a dict with all-zero values.
        """
        with patch(
            "field_check.scanner.language._get_script_distribution",
            return_value={"Latin": 0},
        ):
            result = detect_language("a" * 100)
        assert result == "Unknown"


# ---------------------------------------------------------------------------
# determine_exit_code (report/__init__.py) -- used by cli.py line 266
# ---------------------------------------------------------------------------


class TestDetermineExitCode:
    def test_duplicate_threshold_exceeded(self):
        """Threshold exceeded on duplicate rate."""
        config = FieldCheckConfig(duplicate_critical=0.10)
        inv = InventoryResult(total_files=10)
        dedup = DedupResult(duplicate_percentage=15.0)
        code, breaches = determine_exit_code(config, inv, dedup_result=dedup)
        assert code == 1
        assert len(breaches) == 1

    def test_corrupt_threshold_exceeded(self):
        """Threshold exceeded on corruption rate."""
        config = FieldCheckConfig(corrupt_critical=0.01)
        inv = InventoryResult(total_files=100)
        corruption = CorruptionResult(corrupt_count=2)
        code, breaches = determine_exit_code(config, inv, corruption_result=corruption)
        assert code == 1
        assert len(breaches) == 1

    def test_pii_threshold_exceeded(self):
        """Threshold exceeded on PII rate."""
        config = FieldCheckConfig(pii_critical=0.05)
        inv = InventoryResult(total_files=100)
        pii = PIIScanResult(total_scanned=100, files_with_pii=10)
        code, breaches = determine_exit_code(config, inv, pii_result=pii)
        assert code == 1
        assert len(breaches) == 1

    def test_no_threshold_exceeded(self):
        """No threshold exceeded -> exit 0."""
        config = FieldCheckConfig()
        inv = InventoryResult(total_files=100)
        code, breaches = determine_exit_code(config, inv)
        assert code == 0
        assert breaches == []


# ---------------------------------------------------------------------------
# csv_report.py -- Line 123 (empty default lookups)
# ---------------------------------------------------------------------------


class TestCSVReportEdgeCases:
    def test_csv_report_with_no_optional_results(self):
        """csv_report.py: all lookups return empty defaults gracefully."""
        from field_check.report.csv_report import render_csv_report

        f = [_entry("doc.txt")]
        walk = WalkResult(files=f, total_size=100, scan_root=ROOT)
        inv = _inventory(f, {ROOT / "doc.txt": "text/plain"})

        csv_out = render_csv_report(inv, walk, 1.0)
        assert "doc.txt" in csv_out
        assert "ok" in csv_out


# ---------------------------------------------------------------------------
# Symlink subdir OSError during resolution (line 150-151)
# ---------------------------------------------------------------------------


class TestWalkerSymlinkSubdirOSError:
    def test_symlink_subdir_resolve_oserror(self, tmp_path):
        """scanner/__init__.py line 150-151: OSError during resolve -> pass."""
        config = FieldCheckConfig(exclude=[])

        sub = tmp_path / "link_sub"
        sub.mkdir()

        walk_items = [
            (str(tmp_path), ["link_sub"], []),
        ]

        root_stat = MagicMock()
        root_stat.st_dev = 1
        root_stat.st_ino = 100

        def mock_stat_fn(path, *args, **kwargs):
            return root_stat

        original_is_symlink = Path.is_symlink
        saved_resolve = Path.resolve

        def fake_is_symlink(self):
            if self.name == "link_sub":
                return True
            return original_is_symlink(self)

        def fake_resolve(self):
            if self.name == "link_sub":
                raise OSError("cannot resolve")
            return saved_resolve(self)

        with (
            patch("field_check.scanner.os.walk", return_value=iter(walk_items)),
            patch(
                "field_check.scanner.os.stat",
                side_effect=_make_stat_wrapper(mock_stat_fn),
            ),
            patch.object(Path, "is_symlink", fake_is_symlink),
            patch.object(Path, "resolve", fake_resolve),
        ):
            result = walk_directory(tmp_path, config)

        assert len(result.symlink_loops) == 0


# ---------------------------------------------------------------------------
# text.py -- Line 160: classification = CLASSIFICATION_TEXT_HEAVY
# ---------------------------------------------------------------------------


class TestPDFClassificationTextHeavy:
    def test_text_heavy_classification(self, tmp_path):
        """text.py line 160: chars_per_page > TEXT_HEAVY -> text_heavy."""
        pdf_path = tmp_path / "text_heavy.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        high_chars = CHARS_PER_PAGE_TEXT_HEAVY + 100

        mock_page = MagicMock()
        mock_page.chars = [{"c": "x"}] * high_chars
        mock_page.extract_text.return_value = "x" * high_chars

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.metadata = {}
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with _mock_pdfplumber_open(mock_pdf):
            result = _extract_pdf(str(pdf_path))

        assert result.classification == "text_heavy"
        assert result.chars_per_page > CHARS_PER_PAGE_TEXT_HEAVY


# ---------------------------------------------------------------------------
# text.py -- Line 213: _extract_single PDF branch
# ---------------------------------------------------------------------------


class TestExtractSinglePDF:
    def test_extract_single_pdf(self, tmp_path):
        """text.py line 213: _extract_single dispatches to _extract_pdf."""
        from field_check.scanner.text import _extract_single
        from tests.conftest import create_pdf_with_text

        pdf_path = tmp_path / "test.pdf"
        create_pdf_with_text(pdf_path, "Extract single test")
        result = _extract_single(str(pdf_path), "application/pdf")
        assert result.error is None
        assert result.text_length > 0
