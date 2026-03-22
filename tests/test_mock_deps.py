"""Mock-based tests for optional dependency code paths.

Covers modules that require optional packages (datasketch, semhash, faiss,
textstat, chardet, openpyxl, python-pptx, etc.) by mocking the imports
so the core logic is exercised without the actual packages.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# MinHash+LSH (datasketch mock)
# ---------------------------------------------------------------------------


class TestMinHashMocked:
    """Test MinHash near-duplicate detection with mocked datasketch."""

    @classmethod
    def setup_class(cls) -> None:
        """Pre-import module so patch.dict doesn't remove it on cleanup."""
        import field_check.scanner.minhash  # noqa: F401

    def teardown_method(self) -> None:
        """Restore minhash module after reload-based mocking."""
        import importlib

        from field_check.scanner import minhash

        importlib.reload(minhash)

    def _mock_datasketch(self):
        """Create mock datasketch module with MinHash and MinHashLSH."""
        mock_module = MagicMock()

        class FakeMinHash:
            def __init__(self, num_perm: int = 128) -> None:
                self.values: set[str] = set()

            def update(self, data: bytes) -> None:
                self.values.add(data.decode("utf-8", errors="replace"))

            def jaccard(self, other: FakeMinHash) -> float:
                if not self.values and not other.values:
                    return 1.0
                intersection = self.values & other.values
                union = self.values | other.values
                return len(intersection) / len(union) if union else 0.0

        class FakeMinHashLSH:
            def __init__(self, threshold: float = 0.5, num_perm: int = 128) -> None:
                self.store: dict[str, FakeMinHash] = {}
                self.threshold = threshold

            def insert(self, key: str, mh: FakeMinHash) -> None:
                self.store[key] = mh

            def query(self, mh: FakeMinHash) -> list[str]:
                results = []
                for k, stored in self.store.items():
                    if stored.jaccard(mh) >= self.threshold:
                        results.append(k)
                return results

        mock_module.MinHash = FakeMinHash
        mock_module.MinHashLSH = FakeMinHashLSH
        return mock_module

    def test_clustering_identical_texts(self) -> None:
        mock_ds = self._mock_datasketch()
        with patch.dict("sys.modules", {"datasketch": mock_ds}):
            import importlib

            from field_check.scanner import minhash

            importlib.reload(minhash)

            base = "The quarterly financial report shows strong growth " * 5
            cache = {
                "a.txt": base,
                "b.txt": base,
                "c.txt": "Completely unrelated text about science " * 5,
            }
            result = minhash.detect_near_duplicates_minhash(cache, threshold=0.5)
            assert result.total_analyzed == 3
            assert result.total_clusters >= 1
            found = any(
                "a.txt" in c.paths and "b.txt" in c.paths
                for c in result.clusters
            )
            assert found

    def test_no_duplicates(self) -> None:
        mock_ds = self._mock_datasketch()
        with patch.dict("sys.modules", {"datasketch": mock_ds}):
            import importlib

            from field_check.scanner import minhash

            importlib.reload(minhash)

            cache = {
                "a.txt": "Alpha beta gamma delta epsilon zeta eta " * 5,
                "b.txt": "One two three four five six seven eight " * 5,
            }
            result = minhash.detect_near_duplicates_minhash(
                cache, threshold=0.9
            )
            assert result.total_clusters == 0

    def test_three_way_cluster(self) -> None:
        mock_ds = self._mock_datasketch()
        with patch.dict("sys.modules", {"datasketch": mock_ds}):
            import importlib

            from field_check.scanner import minhash

            importlib.reload(minhash)

            text = "Identical document content for testing purposes " * 5
            cache = {"a.txt": text, "b.txt": text, "c.txt": text}
            result = minhash.detect_near_duplicates_minhash(
                cache, threshold=0.5
            )
            assert result.total_clusters == 1
            assert len(result.clusters[0].paths) == 3

    def test_progress_callback(self) -> None:
        mock_ds = self._mock_datasketch()
        with patch.dict("sys.modules", {"datasketch": mock_ds}):
            import importlib

            from field_check.scanner import minhash

            importlib.reload(minhash)

            calls: list[tuple[int, int]] = []
            cache = {
                "a.txt": "Content A for testing purposes " * 5,
                "b.txt": "Content B for testing purposes " * 5,
            }
            minhash.detect_near_duplicates_minhash(
                cache,
                progress_callback=lambda c, t: calls.append((c, t)),
            )
            assert len(calls) == 2
            assert calls[-1] == (2, 2)

    def test_single_file_returns_early(self) -> None:
        mock_ds = self._mock_datasketch()
        with patch.dict("sys.modules", {"datasketch": mock_ds}):
            import importlib

            from field_check.scanner import minhash

            importlib.reload(minhash)

            result = minhash.detect_near_duplicates_minhash(
                {"a.txt": "Only one file with enough text " * 5}
            )
            assert result.total_analyzed == 1
            assert result.total_clusters == 0

    def test_per_file_exception(self) -> None:
        """Per-file exception in MinHash should not crash the scan."""
        mock_ds = self._mock_datasketch()

        class ExplodingMinHash:
            def __init__(self, num_perm: int = 128) -> None:
                raise RuntimeError("boom")

        mock_ds.MinHash = ExplodingMinHash
        with patch.dict("sys.modules", {"datasketch": mock_ds}):
            import importlib

            from field_check.scanner import minhash

            importlib.reload(minhash)

            cache = {
                "a.txt": "Text content " * 20,
                "b.txt": "More content " * 20,
            }
            result = minhash.detect_near_duplicates_minhash(cache)
            assert result.total_analyzed == 0


# ---------------------------------------------------------------------------
# Semantic Dedup (semhash mock)
# ---------------------------------------------------------------------------


class TestSemanticDedupMocked:
    """Test semantic dedup with mocked semhash."""

    @classmethod
    def setup_class(cls) -> None:
        """Pre-import module so patch.dict doesn't remove it on cleanup."""
        import field_check.scanner.semantic_dedup  # noqa: F401

    def teardown_method(self) -> None:
        """Restore semantic_dedup module after reload-based mocking."""
        import importlib

        from field_check.scanner import semantic_dedup

        importlib.reload(semantic_dedup)

    def _mock_semhash(self, records: list[str]):
        """Create mock semhash module."""
        mock_module = MagicMock()

        text_groups: dict[str, list[int]] = {}
        for i, t in enumerate(records):
            text_groups.setdefault(t, []).append(i)

        selected_items = []
        for text, indices in text_groups.items():
            if len(indices) >= 2:
                dups = [(records[idx], 0.95) for idx in indices[1:]]
                item = SimpleNamespace(record=text, duplicates=dups)
                selected_items.append(item)
            else:
                item = SimpleNamespace(record=text, duplicates=[])
                selected_items.append(item)

        dedup_result = SimpleNamespace(
            selected_with_duplicates=selected_items,
        )

        class FakeSemHash:
            @staticmethod
            def from_records(texts: list[str]) -> FakeSemHash:
                return FakeSemHash()

            def self_deduplicate(self, threshold: float = 0.85) -> object:
                return dedup_result

        mock_module.SemHash = FakeSemHash
        return mock_module

    def test_identical_texts_cluster(self) -> None:
        text = "The quarterly report shows growth and progress " * 5
        cache = {"a.txt": text, "b.txt": text}
        texts_for_mock = [text[:5000], text[:5000]]

        mock_sh = self._mock_semhash(texts_for_mock)
        with patch.dict("sys.modules", {"semhash": mock_sh}):
            import importlib

            from field_check.scanner import semantic_dedup

            importlib.reload(semantic_dedup)

            result = semantic_dedup.detect_semantic_duplicates(
                cache, threshold=0.8
            )
            assert result.total_analyzed == 2
            assert result.total_clusters == 1
            assert "a.txt" in result.clusters[0].paths
            assert "b.txt" in result.clusters[0].paths
            assert result.clusters[0].similarity == 0.95

    def test_no_duplicates(self) -> None:
        cache = {
            "a.txt": "Alpha beta gamma delta epsilon " * 5,
            "b.txt": "One two three four five six seven " * 5,
        }
        texts = [v[:5000] for v in cache.values()]

        mock_sh = self._mock_semhash(texts)
        with patch.dict("sys.modules", {"semhash": mock_sh}):
            import importlib

            from field_check.scanner import semantic_dedup

            importlib.reload(semantic_dedup)

            result = semantic_dedup.detect_semantic_duplicates(cache)
            assert result.total_clusters == 0

    def test_progress_callback(self) -> None:
        text = "Document content for testing " * 5
        cache = {"a.txt": text, "b.txt": text}
        mock_sh = self._mock_semhash([text[:5000], text[:5000]])
        calls: list[tuple[int, int]] = []

        with patch.dict("sys.modules", {"semhash": mock_sh}):
            import importlib

            from field_check.scanner import semantic_dedup

            importlib.reload(semantic_dedup)

            semantic_dedup.detect_semantic_duplicates(
                cache,
                progress_callback=lambda c, t: calls.append((c, t)),
            )
            assert len(calls) == 2

    def test_exception_handling(self) -> None:
        mock_module = MagicMock()
        mock_module.SemHash.from_records.side_effect = RuntimeError(
            "model error"
        )

        with patch.dict("sys.modules", {"semhash": mock_module}):
            import importlib

            from field_check.scanner import semantic_dedup

            importlib.reload(semantic_dedup)

            cache = {
                "a.txt": "Content " * 20,
                "b.txt": "Content " * 20,
            }
            result = semantic_dedup.detect_semantic_duplicates(cache)
            assert result.total_clusters == 0


# ---------------------------------------------------------------------------
# SimHash Faiss candidates (faiss mock)
# ---------------------------------------------------------------------------


class TestSimHashFaissMocked:
    """Test Faiss-backed SimHash candidate search."""

    def test_faiss_candidates_basic(self) -> None:
        """Test _faiss_candidates with mocked faiss + numpy."""
        mock_faiss = MagicMock()

        # Build a lightweight numpy mock with array-like objects
        class FakeArray:
            """Minimal array mock supporting indexing."""

            def __init__(self, data: list) -> None:
                self._data = data

            def __getitem__(self, key):  # type: ignore[no-untyped-def]
                return self._data[key]

            def __setitem__(self, key, val):  # type: ignore[no-untyped-def]
                self._data[key] = val

        mock_np = MagicMock()
        fingerprints = [0b1010101010, 0b1010101010, 0b0101010101]
        bits = 64
        byte_width = bits // 8

        # zeros returns a list-of-lists the function can index into
        zeros_data = FakeArray(
            [bytearray(byte_width) for _ in range(3)]
        )
        mock_np.zeros.return_value = zeros_data
        mock_np.uint8 = "uint8"
        mock_np.frombuffer.side_effect = lambda b, dtype: bytearray(b)

        mock_index = MagicMock()
        mock_faiss.IndexBinaryFlat.return_value = mock_index
        # distance results: items 0,1 are identical (dist 0), item 2 differs
        distances = FakeArray(
            [FakeArray([0, 0, 32]), FakeArray([0, 0, 32]), FakeArray([32, 32, 0])]
        )
        indices = FakeArray(
            [FakeArray([0, 1, 2]), FakeArray([1, 0, 2]), FakeArray([2, 0, 1])]
        )
        mock_index.search.return_value = (distances, indices)

        with patch.dict(
            "sys.modules", {"faiss": mock_faiss, "numpy": mock_np}
        ):
            from field_check.scanner.simhash import _faiss_candidates

            candidates = _faiss_candidates(
                fingerprints, threshold=5, bits=64
            )
            assert candidates is not None
            assert (0, 1) in candidates or (1, 0) in candidates

    def test_faiss_not_installed_returns_none(self) -> None:
        """When faiss is not installed, returns None."""
        from field_check.scanner.simhash import _faiss_candidates

        result = _faiss_candidates([1, 2, 3], threshold=5)
        assert result is None

    def test_faiss_single_fingerprint(self) -> None:
        """Single fingerprint should return empty set."""
        mock_faiss = MagicMock()
        mock_np = MagicMock()

        with patch.dict(
            "sys.modules", {"faiss": mock_faiss, "numpy": mock_np}
        ):
            from field_check.scanner.simhash import _faiss_candidates

            result = _faiss_candidates([42], threshold=5)
            assert result == set()


# ---------------------------------------------------------------------------
# Text Workers — EML, EPUB extraction
# ---------------------------------------------------------------------------


class TestTextWorkersEML:
    """Test EML extraction using stdlib email parser."""

    def test_extract_eml(self, tmp_path: Path) -> None:
        eml_content = (
            "From: alice@example.com\r\n"
            "To: bob@example.com\r\n"
            "Subject: Test Email\r\n"
            "Date: Mon, 1 Jan 2025 00:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Hello, this is the body of the email.\r\n"
        )
        eml_path = tmp_path / "test.eml"
        eml_path.write_bytes(eml_content.encode("utf-8"))

        from field_check.scanner.text_workers import _extract_eml

        result = _extract_eml(str(eml_path))
        assert result.error is None
        assert "Test Email" in result.text
        assert "Hello" in result.text
        assert result.metadata["title"] == "Test Email"
        assert result.metadata["author"] == "alice@example.com"

    def test_extract_eml_error(self) -> None:
        from field_check.scanner.text_workers import _extract_eml

        result = _extract_eml("/nonexistent/file.eml")
        assert result.error is not None


class TestTextWorkersEPUB:
    """Test EPUB extraction using stdlib zipfile."""

    def test_extract_epub(self, tmp_path: Path) -> None:
        epub_path = tmp_path / "test.epub"
        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr(
                "OEBPS/chapter1.xhtml",
                "<html><body><p>Chapter one content.</p></body></html>",
            )
            zf.writestr(
                "OEBPS/chapter2.html",
                "<html><body><p>Chapter two content.</p></body></html>",
            )

        from field_check.scanner.text_workers import _extract_epub

        result = _extract_epub(str(epub_path))
        assert result.error is None
        assert "Chapter one" in result.text
        assert "Chapter two" in result.text

    def test_extract_epub_error(self) -> None:
        from field_check.scanner.text_workers import _extract_epub

        result = _extract_epub("/nonexistent/file.epub")
        assert result.error is not None


class TestTextWorkersXLSX:
    """Test XLSX extraction with mock openpyxl."""

    def test_extract_xlsx_not_installed(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "test.xlsx"
        xlsx.write_bytes(b"fake")
        with patch.dict("sys.modules", {"openpyxl": None}):
            from field_check.scanner.text_workers import _extract_xlsx

            result = _extract_xlsx(str(xlsx))
            assert result.error is not None
            assert "openpyxl" in result.error

    def test_extract_xlsx_error(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "test.xlsx"
        xlsx.write_bytes(b"not a real xlsx")
        from field_check.scanner.text_workers import _extract_xlsx

        result = _extract_xlsx(str(xlsx))
        assert result.error is not None


class TestTextWorkersPPTX:
    """Test PPTX extraction with mock python-pptx."""

    def test_extract_pptx_not_installed(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"fake")
        with patch.dict("sys.modules", {"pptx": None}):
            from field_check.scanner.text_workers import _extract_pptx

            result = _extract_pptx(str(pptx))
            assert result.error is not None
            assert "python-pptx" in result.error

    def test_extract_pptx_error(self, tmp_path: Path) -> None:
        pptx = tmp_path / "test.pptx"
        pptx.write_bytes(b"not a real pptx")
        from field_check.scanner.text_workers import _extract_pptx

        result = _extract_pptx(str(pptx))
        assert result.error is not None


class TestTextWorkersCache:
    """Test _extract_text_for_cache dispatch for new formats."""

    def test_cache_eml(self, tmp_path: Path) -> None:
        eml_content = (
            "From: a@b.com\r\nSubject: Hi\r\n"
            "Content-Type: text/plain\r\n\r\nBody text.\r\n"
        )
        p = tmp_path / "t.eml"
        p.write_bytes(eml_content.encode())

        from field_check.scanner.text_workers import _extract_text_for_cache

        text, _, _, err = _extract_text_for_cache(
            str(p), "message/rfc822"
        )
        assert err is None
        assert "Body text" in text

    def test_cache_epub(self, tmp_path: Path) -> None:
        p = tmp_path / "t.epub"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("ch.xhtml", "<p>Epub text</p>")

        from field_check.scanner.text_workers import _extract_text_for_cache

        text, _, _, err = _extract_text_for_cache(
            str(p), "application/epub+zip"
        )
        assert err is None
        assert "Epub text" in text


class TestExtractSingleDispatch:
    """Test _extract_single dispatch for all MIME types."""

    def test_xlsx_dispatch(self, tmp_path: Path) -> None:
        from field_check.scanner.text_workers import _extract_single

        xlsx_mime = (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        )
        p = tmp_path / "t.xlsx"
        p.write_bytes(b"fake")
        r = _extract_single(str(p), xlsx_mime)
        assert r.error is not None

    def test_pptx_dispatch(self, tmp_path: Path) -> None:
        from field_check.scanner.text_workers import _extract_single

        pptx_mime = (
            "application/vnd.openxmlformats-officedocument"
            ".presentationml.presentation"
        )
        p = tmp_path / "t.pptx"
        p.write_bytes(b"fake")
        r = _extract_single(str(p), pptx_mime)
        assert r.error is not None

    def test_eml_dispatch(self, tmp_path: Path) -> None:
        from field_check.scanner.text_workers import _extract_single

        p = tmp_path / "t.eml"
        p.write_bytes(b"From: a@b\r\nSubject: X\r\n\r\nBody\r\n")
        r = _extract_single(str(p), "message/rfc822")
        assert r.error is None

    def test_epub_dispatch(self, tmp_path: Path) -> None:
        from field_check.scanner.text_workers import _extract_single

        p = tmp_path / "t.epub"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("c.xhtml", "<p>Hi</p>")
        r = _extract_single(str(p), "application/epub+zip")
        assert r.error is None


# ---------------------------------------------------------------------------
# Text Workers — chardet / charset-normalizer encoding detection
# ---------------------------------------------------------------------------


class TestEncodingDetection:
    """Test _detect_encoding fallback chain."""

    def test_chardet_preferred(self) -> None:
        mock_chardet = MagicMock()
        mock_chardet.detect.return_value = {
            "encoding": "utf-8",
            "confidence": 0.99,
        }
        with patch.dict("sys.modules", {"chardet": mock_chardet}):
            from field_check.scanner.text_workers import _detect_encoding

            _text, enc, conf = _detect_encoding(b"hello")
            assert enc == "utf-8"
            assert conf == 0.99

    def test_chardet_low_confidence_falls_through(self) -> None:
        mock_chardet = MagicMock()
        mock_chardet.detect.return_value = {
            "encoding": "ascii",
            "confidence": 0.3,
        }
        with patch.dict("sys.modules", {"chardet": mock_chardet}):
            from field_check.scanner.text_workers import _detect_encoding

            _text, enc, _conf = _detect_encoding(b"hello")
            assert enc is not None

    def test_both_unavailable(self) -> None:
        """When both chardet and charset-normalizer unavailable."""
        with patch.dict(
            "sys.modules",
            {"chardet": None, "charset_normalizer": None},
        ):
            import importlib

            from field_check.scanner import text_workers

            importlib.reload(text_workers)

            _text, enc, _conf = text_workers._detect_encoding(b"hello")
            assert enc == "utf-8"

        # Restore module
        importlib.reload(text_workers)


# ---------------------------------------------------------------------------
# Corruption — truncation and encryption edge cases
# ---------------------------------------------------------------------------


class TestCorruptionEdgeCases:
    """Test corruption detection edge cases."""

    def test_truncated_pdf(self, tmp_path: Path) -> None:
        p = tmp_path / "trunc.pdf"
        p.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
        )
        from field_check.scanner.corruption import _check_truncated_pdf

        assert _check_truncated_pdf(p) is True

    def test_valid_pdf_not_truncated(self, tmp_path: Path) -> None:
        from tests.conftest import create_minimal_pdf

        p = tmp_path / "valid.pdf"
        create_minimal_pdf(p)
        from field_check.scanner.corruption import _check_truncated_pdf

        assert _check_truncated_pdf(p) is False

    def test_truncated_pdf_oserror(self) -> None:
        from field_check.scanner.corruption import _check_truncated_pdf

        assert _check_truncated_pdf(Path("/nonexistent")) is False

    def test_truncated_jpeg(self, tmp_path: Path) -> None:
        p = tmp_path / "trunc.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        from field_check.scanner.corruption import _check_truncated_image

        assert _check_truncated_image(p, "image/jpeg") is True

    def test_valid_jpeg_not_truncated(self, tmp_path: Path) -> None:
        p = tmp_path / "valid.jpg"
        p.write_bytes(
            b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
        )
        from field_check.scanner.corruption import _check_truncated_image

        assert _check_truncated_image(p, "image/jpeg") is False

    def test_truncated_png(self, tmp_path: Path) -> None:
        p = tmp_path / "trunc.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        from field_check.scanner.corruption import _check_truncated_image

        assert _check_truncated_image(p, "image/png") is True

    def test_valid_png_not_truncated(self, tmp_path: Path) -> None:
        from tests.conftest import create_minimal_png

        p = tmp_path / "valid.png"
        create_minimal_png(p)
        from field_check.scanner.corruption import _check_truncated_image

        assert _check_truncated_image(p, "image/png") is False

    def test_truncated_image_small_file(self, tmp_path: Path) -> None:
        p = tmp_path / "tiny.jpg"
        p.write_bytes(b"\xff\xd8\xff")
        from field_check.scanner.corruption import _check_truncated_image

        assert _check_truncated_image(p, "image/jpeg") is False

    def test_truncated_image_unsupported_type(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "file.gif"
        p.write_bytes(b"GIF89a" + b"\x00" * 100)
        from field_check.scanner.corruption import _check_truncated_image

        assert _check_truncated_image(p, "image/gif") is False

    def test_docx_integrity_valid(self, tmp_path: Path) -> None:
        from tests.conftest import create_minimal_docx

        p = tmp_path / "valid.docx"
        create_minimal_docx(p, text="Valid document")
        from field_check.scanner.corruption import _check_docx_integrity

        assert _check_docx_integrity(p) is None

    def test_docx_integrity_bad_zip(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.docx"
        p.write_bytes(b"not a zip")
        from field_check.scanner.corruption import _check_docx_integrity

        result = _check_docx_integrity(p)
        assert result is not None and "ZIP" in result

    def test_docx_missing_content_types(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.docx"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("word/document.xml", "<doc/>")
        from field_check.scanner.corruption import _check_docx_integrity

        result = _check_docx_integrity(p)
        assert result is not None and "Content_Types" in result

    def test_encrypted_office_not_installed(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "test.docx"
        p.write_bytes(b"fake")
        from field_check.scanner.corruption import _check_encrypted_office

        result = _check_encrypted_office(p)
        assert result is False

    def test_crash_isolation(self, tmp_path: Path) -> None:
        """Corruption check loop survives per-file exceptions."""
        from field_check.scanner import FileEntry, WalkResult
        from field_check.scanner.corruption import check_corruption

        p = tmp_path / "crash.bin"
        p.write_bytes(b"\x00" * 100)
        entry = FileEntry(
            path=p,
            relative_path=Path("crash.bin"),
            size=100,
            mtime=1.0,
            ctime=1.0,
            is_symlink=False,
        )
        walk = WalkResult(
            files=[entry], total_size=100, scan_root=tmp_path
        )
        with patch(
            "field_check.scanner.corruption._check_single_file",
            side_effect=RuntimeError("boom"),
        ):
            result = check_corruption(walk)
            assert result.unreadable_count == 1

    def test_encrypted_pdf_in_tail(self, tmp_path: Path) -> None:
        p = tmp_path / "enc_tail.pdf"
        head = b"%PDF-1.4\n" + b"x" * 5000
        tail = b"/Encrypt something\n%%EOF"
        p.write_bytes(head + tail)
        from field_check.scanner.corruption import _check_encrypted_pdf

        assert _check_encrypted_pdf(p) is True


# ---------------------------------------------------------------------------
# PII Helpers — validator coverage
# ---------------------------------------------------------------------------


class TestPIIValidatorEdgeCases:
    """Test PII validator edge cases."""

    def test_luhn_short_number(self) -> None:
        from field_check.scanner.pii_helpers import luhn_check

        assert luhn_check("123") is False

    def test_luhn_long_number(self) -> None:
        from field_check.scanner.pii_helpers import luhn_check

        assert luhn_check("1" * 25) is False

    def test_validate_phone_not_installed(self) -> None:
        with patch.dict("sys.modules", {"phonenumbers": None}):
            from field_check.scanner.pii_helpers import validate_phone

            assert validate_phone("555-123-4567") is True

    def test_validate_phone_parse_error(self) -> None:
        mock_pn = MagicMock()
        mock_pn.parse.side_effect = Exception("parse error")
        with patch.dict("sys.modules", {"phonenumbers": mock_pn}):
            from field_check.scanner.pii_helpers import validate_phone

            assert validate_phone("not-a-number") is False

    def test_validate_iban_without_stdnum(self) -> None:
        with patch.dict(
            "sys.modules", {"stdnum": None, "stdnum.iban": None}
        ):
            from field_check.scanner.pii_helpers import validate_iban

            assert validate_iban("GB29 NWBK 6016 1331 9268 19")
            assert not validate_iban("GB29")

    def test_validate_de_tax_id_not_installed(self) -> None:
        with patch.dict(
            "sys.modules",
            {"stdnum": None, "stdnum.de": None, "stdnum.de.idnr": None},
        ):
            from field_check.scanner.pii_helpers import validate_de_tax_id

            assert validate_de_tax_id("12345678901") is True

    def test_validate_es_dni_not_installed(self) -> None:
        with patch.dict(
            "sys.modules",
            {"stdnum": None, "stdnum.es": None, "stdnum.es.dni": None},
        ):
            from field_check.scanner.pii_helpers import validate_es_dni

            assert validate_es_dni("12345678A") is True

    def test_context_proximity_after_match(self) -> None:
        from field_check.scanner.pii_helpers import (
            CONTEXT_CONFIG,
            compute_context_confidence,
        )

        line = (
            "My number is 123-45-6789 and this is "
            "my social security number"
        )
        conf = compute_context_confidence(
            line, 13, 24, "ssn", CONTEXT_CONFIG
        )
        assert conf > 0.5

    def test_context_suppress_word_after(self) -> None:
        from field_check.scanner.pii_helpers import (
            CONTEXT_CONFIG,
            compute_context_confidence,
        )

        line = "Number 123-45-6789 is the order reference code"
        conf = compute_context_confidence(
            line, 7, 18, "ssn", CONTEXT_CONFIG
        )
        assert conf < 0.5


# ---------------------------------------------------------------------------
# Inventory — per-file crash isolation
# ---------------------------------------------------------------------------


class TestInventoryCrashIsolation:
    """Test inventory analysis per-file crash isolation."""

    def test_inventory_survives_exception(
        self, tmp_path: Path
    ) -> None:
        from field_check.scanner import FileEntry, WalkResult
        from field_check.scanner.inventory import analyze_inventory

        p = tmp_path / "crash.bin"
        p.write_bytes(b"\x00" * 100)
        entry = FileEntry(
            path=p,
            relative_path=Path("crash.bin"),
            size=100,
            mtime=1.0,
            ctime=1.0,
            is_symlink=False,
        )
        walk = WalkResult(
            files=[entry], total_size=100, scan_root=tmp_path
        )
        with patch(
            "field_check.scanner.inventory._detect_file_type",
            side_effect=RuntimeError("boom"),
        ):
            result = analyze_inventory(walk)
            assert result.total_files == 1
            assert result.type_detection_errors == 1
            assert result.file_types[p] == "application/octet-stream"


# ---------------------------------------------------------------------------
# Readability — total_checked fix verification
# ---------------------------------------------------------------------------


class TestReadabilityFixed:
    """Verify total_checked only incremented on success."""

    def test_total_checked_excludes_failures(self) -> None:
        mock_ts = MagicMock()
        call_count = 0

        def fake_flesch(text: str) -> float:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("scoring failed")
            return 65.0

        mock_ts.flesch_reading_ease = fake_flesch

        with patch.dict("sys.modules", {"textstat": mock_ts}):
            import importlib

            from field_check.scanner import readability

            importlib.reload(readability)

            result = readability.analyze_readability(
                {"a.txt": "A" * 300, "b.txt": "B" * 300}
            )
            assert result.total_checked == 1
            assert result.avg_flesch_score == 65.0


# ---------------------------------------------------------------------------
# PDF oxide fast extraction
# ---------------------------------------------------------------------------


class TestPdfOxideFallback:
    """Test pdf_oxide -> pdfplumber fallback chain."""

    def test_pdf_oxide_not_installed(self, tmp_path: Path) -> None:
        from tests.conftest import create_pdf_with_text

        p = tmp_path / "test.pdf"
        create_pdf_with_text(p, "oxide test")

        from field_check.scanner.text_workers import (
            _extract_pdf_text_fast,
        )

        text, _enc, _conf, _err = _extract_pdf_text_fast(str(p))
        assert "oxide test" in text

    def test_pdf_oxide_exception_fallback(
        self, tmp_path: Path
    ) -> None:
        from tests.conftest import create_pdf_with_text

        p = tmp_path / "test.pdf"
        create_pdf_with_text(p, "fallback test")

        mock_oxide = MagicMock()
        mock_oxide.PdfDocument.side_effect = RuntimeError("err")

        with patch.dict("sys.modules", {"pdf_oxide": mock_oxide}):
            from field_check.scanner.text_workers import (
                _extract_pdf_text_fast,
            )

            text, _, _, _ = _extract_pdf_text_fast(str(p))
            assert "fallback test" in text
