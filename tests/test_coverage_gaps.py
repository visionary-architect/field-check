"""Tests targeting remaining coverage gaps across multiple modules."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from field_check.cli import main
from field_check.config import FieldCheckConfig, load_config
from field_check.report import generate_report
from field_check.report.csv_report import render_csv_report
from field_check.report.json_report import _try_relative, render_json_report
from field_check.scanner import FileEntry, WalkResult
from field_check.scanner.corruption import (
    _check_encrypted_pdf,
    _check_encrypted_zip,
    _check_magic_bytes,
)
from field_check.scanner.dedup import compute_hashes
from field_check.scanner.encoding import EncodingFileResult, EncodingResult
from field_check.scanner.inventory import (
    AgeDistribution,
    DirectoryStructure,
    InventoryResult,
    SizeDistribution,
    _detect_file_type,
)
from field_check.scanner.language import (
    LanguageFileResult,
    LanguageResult,
    _detect_latin_language,
    _get_script_distribution,
    analyze_languages,
    detect_language,
)
from field_check.scanner.pii import (
    PIIFileResult,
    PIIScanResult,
    _aggregate_file_result,
    _scan_single_file,
    _scan_single_file_from_specs,
    _scan_text_for_pii,
)
from field_check.scanner.sampling import SampleResult
from field_check.scanner.text import TextResult, _page_count_bucket
from field_check.scanner.text_workers import (
    _extract_docx,
    _extract_single,
    _extract_text_for_cache,
)

ROOT = Path("/corpus")


def _e(name: str, size: int = 100) -> FileEntry:
    return FileEntry(
        path=ROOT / name,
        relative_path=Path(name),
        size=size,
        mtime=1.7e9,
        ctime=1.7e9,
        is_symlink=False,
    )


def _inv(files: list[FileEntry], types: dict) -> InventoryResult:
    return InventoryResult(
        total_files=len(files),
        total_size=sum(f.size for f in files),
        file_types=types,
        size_distribution=SizeDistribution(),
        age_distribution=AgeDistribution(),
        dir_structure=DirectoryStructure(total_dirs=1),
    )


def _samp(files: list[FileEntry]) -> SampleResult:
    return SampleResult(
        selected_files=files,
        total_sample_size=len(files),
        total_population_size=len(files),
        sampling_rate=1.0,
        is_census=True,
    )


def _mock_pool(module: str, futures: list, submit_side=None):
    """Context manager pair for mocking ProcessPoolExecutor + as_completed."""
    pool_patch = patch(f"{module}.ProcessPoolExecutor")
    comp_patch = patch(f"{module}.as_completed", return_value=iter(futures))

    class _Ctx:
        def __enter__(self):
            cls = pool_patch.start()
            pool = MagicMock()
            cls.return_value.__enter__ = MagicMock(return_value=pool)
            cls.return_value.__exit__ = MagicMock(return_value=False)
            if submit_side is not None:
                pool.submit.side_effect = submit_side
            elif len(futures) == 1:
                pool.submit.return_value = futures[0]
            else:
                pool.submit.side_effect = futures
            comp_patch.start()
            return pool

        def __exit__(self, *a):
            comp_patch.stop()
            pool_patch.stop()

    return _Ctx()


# -- text.py -----------------------------------------------------------------


class TestTextGaps:
    def test_page_count_bucket_over_500(self):
        assert _page_count_bucket(999) == ">500 pages"

    def test_extract_single_docx(self, tmp_path):
        from tests.conftest import create_minimal_docx

        p = tmp_path / "t.docx"
        create_minimal_docx(p, text="hi")
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert _extract_single(str(p), mime).error is None

    def test_extract_single_unsupported(self):
        r = _extract_single("/x", "application/octet-stream")
        assert "Unsupported" in r.error

    def test_extract_docx_error(self, tmp_path):
        p = tmp_path / "bad.docx"
        p.write_bytes(b"bad")
        assert _extract_docx(str(p)).error is not None

    def test_cache_pdf_branch(self, tmp_path):
        from tests.conftest import create_pdf_with_text

        p = tmp_path / "c.pdf"
        create_pdf_with_text(p, "cache test")
        text, enc, _, err = _extract_text_for_cache(str(p), "application/pdf")
        assert err is None and "cache test" in text and enc is None

    def test_cache_docx_branch(self, tmp_path):
        from tests.conftest import create_minimal_docx

        p = tmp_path / "c.docx"
        create_minimal_docx(p, text="docx cache")
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        text, _, _, err = _extract_text_for_cache(str(p), mime)
        assert err is None and "docx cache" in text

    def test_cache_plain_text_branch(self, tmp_path):
        p = tmp_path / "c.txt"
        p.write_text("plain", encoding="utf-8")
        _text, enc, _, err = _extract_text_for_cache(str(p), "text/plain")
        assert err is None and enc is not None

    def test_cache_exception_branch(self):
        _, _, _, err = _extract_text_for_cache("/no/file.pdf", "application/pdf")
        assert err is not None

    def test_extract_text_timeout(self):
        from field_check.scanner.text import extract_text

        f = [_e("d.pdf")]
        inv = _inv(f, {ROOT / "d.pdf": "application/pdf"})
        fut = MagicMock()
        fut.result.side_effect = TimeoutError()
        with _mock_pool("field_check.scanner.text", [fut]):
            r = extract_text(_samp(f), inv, max_workers=1)
        assert r.timeout_errors == 1 and r.extraction_errors == 1

    def test_extract_text_exception(self):
        from field_check.scanner.text import extract_text

        f = [_e("d.pdf")]
        inv = _inv(f, {ROOT / "d.pdf": "application/pdf"})
        fut = MagicMock()
        fut.result.side_effect = RuntimeError("x")
        with _mock_pool("field_check.scanner.text", [fut]):
            r = extract_text(_samp(f), inv, max_workers=1)
        assert r.extraction_errors == 1

    def test_mixed_scan_and_content_counts(self):
        from field_check.scanner.text import extract_text

        f = [_e("a.pdf"), _e("b.pdf")]
        inv = _inv(f, {ROOT / "a.pdf": "application/pdf", ROOT / "b.pdf": "application/pdf"})
        fa = MagicMock()
        fa.result.return_value = TextResult(
            path=str(ROOT / "a.pdf"), is_mixed_scan=True, classification="mixed"
        )
        fb = MagicMock()
        fb.result.return_value = TextResult(path=str(ROOT / "b.pdf"), error="broken")
        with _mock_pool("field_check.scanner.text", [fa, fb]):
            r = extract_text(_samp(f), inv, max_workers=1)
        assert r.mixed_scan_count == 1 and r.mixed_content_count == 1
        assert r.extraction_errors == 1

    def test_build_cache_empty_extractable(self):
        from field_check.scanner.text import build_text_cache

        f = [_e("i.png")]
        r = build_text_cache(_samp(f), _inv(f, {ROOT / "i.png": "image/png"}))
        assert r.total_extracted == 0

    def test_build_cache_timeout_and_exception(self):
        from field_check.scanner.text import build_text_cache

        f = [_e("a.txt"), _e("b.txt")]
        inv = _inv(f, {ROOT / "a.txt": "text/plain", ROOT / "b.txt": "text/plain"})
        ft = MagicMock()
        ft.result.side_effect = TimeoutError()
        fc = MagicMock()
        fc.result.side_effect = RuntimeError()
        with _mock_pool("field_check.scanner.text", [ft, fc]):
            r = build_text_cache(_samp(f), inv, max_workers=1)
        assert r.extraction_errors == 2

    def test_build_cache_error_in_result(self):
        from field_check.scanner.text import build_text_cache

        f = [_e("a.txt")]
        inv = _inv(f, {ROOT / "a.txt": "text/plain"})
        fut = MagicMock()
        fut.result.return_value = ("", None, 0.0, "err")
        with _mock_pool("field_check.scanner.text", [fut]):
            r = build_text_cache(_samp(f), inv, max_workers=1)
        assert r.extraction_errors == 1


# -- pii.py ------------------------------------------------------------------


class TestPIIGaps:
    def test_scan_text_empty(self):
        c = [("e", "E", re.compile(r"\S+@\S+"), None)]
        assert _scan_text_for_pii("/f", "", c, False).matches_by_type == {}

    def test_scan_text_luhn_skip(self):
        c = [("cc", "CC", re.compile(r"\b\d{16}\b"), "luhn")]
        r = _scan_text_for_pii("/f", "1234567890123456", c, False)
        assert r.matches_by_type.get("cc", 0) == 0

    def test_scan_text_with_samples(self):
        c = [("e", "E", re.compile(r"\S+@\S+"), None)]
        r = _scan_text_for_pii("/f", "a@b.com", c, True)
        assert len(r.sample_matches) == 1

    def test_scan_single_file_empty(self, tmp_path):
        p = tmp_path / "e.txt"
        p.write_text("", encoding="utf-8")
        c = [("e", "E", re.compile(r"\S+@\S+"), None)]
        assert _scan_single_file(str(p), "text/plain", c, False).matches_by_type == {}

    def test_scan_single_file_exception(self):
        c = [("e", "E", re.compile(r"\S+@\S+"), None)]
        assert _scan_single_file("/no/f", "text/plain", c, False).error is not None

    def test_scan_single_file_luhn_skip(self, tmp_path):
        p = tmp_path / "cc.txt"
        p.write_text("1234567890123456\n", encoding="utf-8")
        c = [("cc", "CC", re.compile(r"\b\d{16}\b"), "luhn")]
        assert _scan_single_file(str(p), "text/plain", c, False).matches_by_type.get("cc", 0) == 0

    def test_scan_single_file_from_specs_ok(self, tmp_path):
        p = tmp_path / "p.txt"
        p.write_text("a@b.com\n", encoding="utf-8")
        r = _scan_single_file_from_specs(
            str(p), "text/plain", [("e", "E", r"\S+@\S+", None)], False
        )
        assert r.matches_by_type.get("e", 0) >= 1

    def test_aggregate_error(self):
        agg = PIIScanResult()
        _aggregate_file_result(agg, PIIFileResult(path="/e", error="err"))
        assert agg.scan_errors == 1

    def test_text_cache_fallback(self):
        from field_check.scanner.pii import scan_pii

        f = [_e("a.txt")]
        inv = _inv(f, {ROOT / "a.txt": "text/plain"})
        fut = MagicMock()
        fut.result.return_value = PIIFileResult(path=str(ROOT / "a.txt"))
        with _mock_pool("field_check.scanner.pii", [fut]):
            r = scan_pii(_samp(f), inv, FieldCheckConfig(), text_cache={"other": "text"})
        assert r.total_scanned == 1

    def test_pool_timeout_and_exception(self):
        from field_check.scanner.pii import scan_pii

        f = [_e("a.txt"), _e("b.txt")]
        inv = _inv(f, {ROOT / "a.txt": "text/plain", ROOT / "b.txt": "text/plain"})
        ft = MagicMock()
        ft.result.side_effect = TimeoutError()
        fc = MagicMock()
        fc.result.side_effect = RuntimeError()
        with _mock_pool("field_check.scanner.pii", [ft, fc]):
            r = scan_pii(_samp(f), inv, FieldCheckConfig())
        assert r.scan_errors == 2


# -- cli.py ------------------------------------------------------------------


class TestCLIGaps:
    def test_not_directory(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("x", encoding="utf-8")
        assert CliRunner().invoke(main, ["scan", str(p)]).exit_code == 2

    def test_sampling_rate_flag(self, tmp_path):
        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        r = CliRunner().invoke(main, ["scan", str(tmp_path), "--sampling-rate", "0.5"])
        assert r.exit_code == 0

    def test_show_pii_samples_flag(self, tmp_path):
        (tmp_path / "f.txt").write_text("x", encoding="utf-8")
        r = CliRunner().invoke(main, ["scan", str(tmp_path), "--show-pii-samples"])
        assert r.exit_code == 0

    def test_unsupported_format(self):
        from rich.console import Console

        with pytest.raises(ValueError, match="not yet supported"):
            generate_report("bad", InventoryResult(), WalkResult(), 1.0, None, Console())


# -- language.py --------------------------------------------------------------


class TestLanguageGaps:
    def test_empty_words_latin_unknown(self):
        assert _detect_latin_language("12345 67890") == "Latin (Unknown)"

    def test_skip_punct_ranges(self):
        assert _get_script_distribution("[\\]^_`{|}~") == {}

    def test_total_classified_zero(self):
        assert detect_language("1234567890!@#$%^&*() " * 5) == "Unknown"

    def test_mixed_script(self):
        text = (
            "\u4e00\u4e01\u4e02\u4e03\u4e04"
            "abcde"
            "\u0627\u0628\u0629\u062a\u062b"
            "\u4e05\u4e06"
            "fg"
            "\u062c\u062d"
        )
        assert detect_language(text) == "Mixed Script"

    def test_cjk_pure(self):
        assert detect_language("\u4e00\u4e01\u4e02\u4e03\u4e04" * 10) == "CJK"

    def test_arabic(self):
        assert detect_language("\u0627\u0628\u0629\u062a\u062b" * 10) == "Arabic"

    def test_devanagari(self):
        assert detect_language("\u0905\u0906\u0907\u0908\u0909" * 10) == "Devanagari"

    def test_cyrillic(self):
        assert detect_language("\u0410\u0411\u0412\u0413\u0414" * 10) == "Cyrillic"

    def test_japanese_kana(self):
        assert detect_language("\u3042\u3044\u3046\u3048\u304a" * 10) == "Japanese"

    def test_cjk_with_hangul(self):
        text = "\u4e00\u4e01\u4e02\u4e03\u4e04" * 8 + "\uac00\uac01"
        assert detect_language(text) == "Korean"

    def test_detection_exception(self):
        with patch("field_check.scanner.language.detect_language", side_effect=RuntimeError):
            assert analyze_languages({"f": "text"}).detection_errors == 1


# -- config.py ----------------------------------------------------------------


class TestConfigGaps:
    def test_pii_not_dict(self, tmp_path):
        f = tmp_path / ".field-check.yaml"
        f.write_text("pii: x\n", encoding="utf-8")
        assert load_config(tmp_path, f).pii_custom_patterns == []

    def test_invalid_regex(self, tmp_path):
        f = tmp_path / ".field-check.yaml"
        f.write_text(
            'pii:\n  custom_patterns:\n    - name: "b"\n      pattern: "[bad"\n', encoding="utf-8"
        )
        assert load_config(tmp_path, f).pii_custom_patterns == []

    def test_missing_keys(self, tmp_path):
        f = tmp_path / ".field-check.yaml"
        f.write_text("pii:\n  custom_patterns:\n    - foo: bar\n", encoding="utf-8")
        assert load_config(tmp_path, f).pii_custom_patterns == []

    def test_valid_custom_pattern(self, tmp_path):
        f = tmp_path / ".field-check.yaml"
        f.write_text(
            'pii:\n  custom_patterns:\n    - name: "cid"\n      pattern: "ID-\\\\d{6}"\n',
            encoding="utf-8",
        )
        c = load_config(tmp_path, f)
        assert len(c.pii_custom_patterns) == 1

    def test_sampling_min_per_type(self, tmp_path):
        f = tmp_path / ".field-check.yaml"
        f.write_text("sampling:\n  min_per_type: 50\n", encoding="utf-8")
        assert load_config(tmp_path, f).sampling_min_per_type == 50


# -- json_report.py -----------------------------------------------------------


class TestJSONGaps:
    def test_try_relative_value_error(self):
        assert _try_relative("/other/path", Path("/root")) == "/other/path"

    def test_encoding_section(self):
        f = [_e("d.txt")]
        walk = WalkResult(files=f, total_size=100, scan_root=ROOT)
        enc = EncodingResult(
            total_analyzed=1,
            encoding_distribution={"utf-8": 1},
            file_results=[
                EncodingFileResult(path=str(ROOT / "d.txt"), encoding="utf-8", confidence=0.99)
            ],
        )
        data = json.loads(
            render_json_report(
                _inv(f, {ROOT / "d.txt": "text/plain"}), walk, 1.0, encoding_result=enc
            )
        )
        assert data["summary"]["encoding"]["total_analyzed"] == 1


# -- encoding.py --------------------------------------------------------------


class TestEncodingGaps:
    def test_normalize_unknown_encoding(self):
        from field_check.scanner.encoding import _normalize_encoding

        # Unknown codec falls back to lowercased name
        assert _normalize_encoding("totally-fake-codec-xyz") == "totally-fake-codec-xyz"

    def test_normalize_codecs_lookup(self):
        from field_check.scanner.encoding import _normalize_encoding

        # codecs.lookup handles alias resolution
        assert _normalize_encoding("latin-1") == "iso-8859-1"
        assert _normalize_encoding("ASCII") == "utf-8"
        assert _normalize_encoding("CP1252") == "windows-1252"


# -- corruption.py ------------------------------------------------------------


class TestCorruptionGaps:
    def test_unknown_mime(self):
        assert _check_magic_bytes(b"\x00", "application/x-unk") is True

    def test_encrypted_pdf_oserror(self):
        assert _check_encrypted_pdf(Path("/no/f.pdf")) is False

    def test_encrypted_zip_oserror(self):
        assert _check_encrypted_zip(Path("/no/f.zip")) is False

    def test_encrypted_zip_short(self, tmp_path):
        p = tmp_path / "s.zip"
        p.write_bytes(b"PK\x03\x04\x00")
        assert _check_encrypted_zip(p) is False


# -- csv_report.py ------------------------------------------------------------


class TestCSVGaps:
    def test_all_lookups(self):
        f = [_e("d.txt")]
        walk = WalkResult(files=f, total_size=100, scan_root=ROOT)
        out = render_csv_report(
            _inv(f, {ROOT / "d.txt": "text/plain"}),
            walk,
            1.0,
            pii_result=PIIScanResult(
                file_results=[PIIFileResult(path=str(ROOT / "d.txt"), matches_by_type={"email": 2})]
            ),
            language_result=LanguageResult(
                file_results=[
                    LanguageFileResult(path=str(ROOT / "d.txt"), language="English", script="Latin")
                ]
            ),
            encoding_result=EncodingResult(
                file_results=[
                    EncodingFileResult(path=str(ROOT / "d.txt"), encoding="utf-8", confidence=0.99)
                ]
            ),
        )
        assert "English" in out and "utf-8" in out and "email" in out


# -- dedup.py -----------------------------------------------------------------


class TestDedupGaps:
    def test_hash_error(self, tmp_path):
        p = tmp_path / "x.bin"
        p.write_bytes(b"d")
        e = _e("x.bin")
        e.path = p
        # Need two files with same size so size pre-filter picks them up
        e2 = _e("y.bin")
        e2.path = tmp_path / "y.bin"
        (tmp_path / "y.bin").write_bytes(b"e")
        with patch("field_check.scanner.dedup._hash_file", side_effect=PermissionError):
            assert compute_hashes(WalkResult(files=[e, e2], total_size=2)).hash_errors == 2


# -- inventory.py -------------------------------------------------------------


class TestInventoryGaps:
    def test_extension_shortcircuit(self, tmp_path):
        """Known text extensions skip filetype.guess entirely."""
        p = tmp_path / "r.txt"
        p.write_text("x", encoding="utf-8")
        mime, had_error = _detect_file_type(p)
        assert mime == "text/plain"
        assert had_error is False

    def test_filetype_guess_none_fallback(self, tmp_path):
        """Unknown extension + filetype returns None → octet-stream."""
        p = tmp_path / "data.xyz"
        p.write_bytes(b"\x00\x01\x02")
        with patch("filetype.guess", return_value=None):
            mime, had_error = _detect_file_type(p)
            assert mime == "application/octet-stream"
            assert had_error is False

    def test_filetype_oserror(self, tmp_path):
        """Unknown extension + filetype raises → octet-stream."""
        p = tmp_path / "data.xyz"
        p.write_bytes(b"\x00\x01\x02")
        with patch("filetype.guess", side_effect=PermissionError):
            mime, had_error = _detect_file_type(p)
            assert mime == "application/octet-stream"
            assert had_error is True


# -- report/__init__.py -------------------------------------------------------


class TestReportGaps:
    def test_unsupported_format(self):
        from rich.console import Console

        with pytest.raises(ValueError, match="not yet supported"):
            generate_report("pdf", InventoryResult(), WalkResult(), 1.0, None, Console())
