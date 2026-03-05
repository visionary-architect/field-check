"""Tests for language detection, encoding analysis, and shared text cache."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.scanner import walk_directory
from field_check.scanner.encoding import analyze_encodings
from field_check.scanner.inventory import analyze_inventory
from field_check.scanner.language import analyze_languages, detect_language
from field_check.scanner.pii import scan_pii
from field_check.scanner.sampling import select_sample
from field_check.scanner.text import build_text_cache
from tests.conftest import create_minimal_docx, create_pdf_with_text

# ---------------------------------------------------------------------------
# Language detection unit tests
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """Test single-text language detection."""

    def test_detect_english(self) -> None:
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "This is a test of the English detection system."
        )
        assert detect_language(text) == "English"

    def test_detect_spanish(self) -> None:
        text = (
            "El gato está en la mesa. Los perros son grandes y fuertes. "
            "Esta es una prueba del sistema de detección."
        )
        assert detect_language(text) == "Spanish"

    def test_detect_french(self) -> None:
        text = (
            "Le chat est sur la table. Les chiens sont grands et forts. "
            "Ceci est un test du système de détection."
        )
        assert detect_language(text) == "French"

    def test_detect_german(self) -> None:
        text = (
            "Der Hund ist auf dem Tisch. Die Katzen sind nicht im Haus. "
            "Das ist ein Test für die Spracherkennung."
        )
        assert detect_language(text) == "German"

    def test_detect_portuguese(self) -> None:
        text = (
            "O gato está na mesa. Os cães são grandes e fortes. "
            "Este é um teste do sistema de detecção de idiomas."
        )
        assert detect_language(text) == "Portuguese"

    def test_detect_italian(self) -> None:
        text = (
            "Il gatto è sul tavolo. I cani sono grandi e forti. "
            "Questo è un test del sistema di rilevamento della lingua."
        )
        assert detect_language(text) == "Italian"

    def test_detect_dutch(self) -> None:
        text = (
            "De kat is op de tafel. De honden zijn groot en sterk. "
            "Dit is een test van het taaldetectiesysteem voor ons project."
        )
        assert detect_language(text) == "Dutch"

    def test_detect_cjk(self) -> None:
        text = "这是一个中文测试句子。我们正在测试语言检测系统的准确性。"
        assert detect_language(text) == "CJK"

    def test_detect_japanese(self) -> None:
        text = "これはテストです。日本語の検出を確認しています。"
        assert detect_language(text) == "Japanese"

    def test_detect_korean(self) -> None:
        text = "한국어 테스트입니다. 언어 감지 시스템을 확인합니다."
        assert detect_language(text) == "Korean"

    def test_detect_arabic(self) -> None:
        text = "هذا نص باللغة العربية لاختبار نظام الكشف عن اللغة في البرنامج."
        assert detect_language(text) == "Arabic"

    def test_detect_cyrillic(self) -> None:
        text = "Это текст на русском языке для тестирования системы определения языка."
        assert detect_language(text) == "Cyrillic"

    def test_detect_short_text(self) -> None:
        assert detect_language("Hello") == "Unknown"
        assert detect_language("Hi there!") == "Unknown"

    def test_detect_empty_text(self) -> None:
        assert detect_language("") == "Unknown"
        assert detect_language("   ") == "Unknown"

    def test_detect_numbers_only(self) -> None:
        assert detect_language("12345 67890 11111 22222") == "Unknown"

    def test_latin_unknown_insufficient_stopwords(self) -> None:
        # Made-up Latin-script text with no real stop-words
        text = "xyzzy plugh quux garply corge grault waldo thud " * 3
        result = detect_language(text)
        assert result == "Latin (Unknown)"


# ---------------------------------------------------------------------------
# Language analysis (aggregate) tests
# ---------------------------------------------------------------------------


class TestAnalyzeLanguages:
    """Test aggregate language analysis."""

    def test_empty_cache(self) -> None:
        result = analyze_languages({})
        assert result.total_analyzed == 0
        assert result.language_distribution == {}

    def test_single_language(self) -> None:
        cache = {
            "a.txt": "The quick brown fox jumps over the lazy dog and more text here.",
            "b.txt": "This is another English document with enough words for detection.",
        }
        result = analyze_languages(cache)
        assert result.total_analyzed == 2
        assert result.language_distribution.get("English") == 2

    def test_multi_language(self) -> None:
        cache = {
            "en.txt": "The quick brown fox jumps over the lazy dog and more text here.",
            "es.txt": (
                "El gato está en la mesa. Los perros son grandes y fuertes. "
                "Esta es una prueba."
            ),
            "fr.txt": (
                "Le chat est sur la table. Les chiens sont grands et forts. "
                "Ceci est un test."
            ),
        }
        result = analyze_languages(cache)
        assert result.total_analyzed == 3
        assert result.language_distribution.get("English") == 1
        assert result.language_distribution.get("Spanish") == 1
        assert result.language_distribution.get("French") == 1

    def test_progress_callback(self) -> None:
        calls: list[tuple[int, int]] = []
        cache = {
            "a.txt": "The quick brown fox jumps over the lazy dog and more text here.",
            "b.txt": "This is another English document with enough words for detection.",
        }
        analyze_languages(cache, progress_callback=lambda c, t: calls.append((c, t)))
        assert len(calls) == 2
        assert calls[-1] == (2, 2)


# ---------------------------------------------------------------------------
# Encoding analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeEncodings:
    """Test encoding result aggregation."""

    def test_empty_map(self) -> None:
        result = analyze_encodings({})
        assert result.total_analyzed == 0
        assert result.encoding_distribution == {}

    def test_single_encoding(self) -> None:
        result = analyze_encodings({
            "a.txt": ("utf-8", 0.99),
            "b.txt": ("utf-8", 0.95),
        })
        assert result.total_analyzed == 2
        assert result.encoding_distribution == {"utf-8": 2}

    def test_mixed_encodings(self) -> None:
        result = analyze_encodings({
            "a.txt": ("utf-8", 0.99),
            "b.txt": ("iso-8859-1", 0.85),
            "c.txt": ("windows-1252", 0.90),
        })
        assert result.total_analyzed == 3
        assert result.encoding_distribution["utf-8"] == 1
        assert result.encoding_distribution["iso-8859-1"] == 1
        assert result.encoding_distribution["windows-1252"] == 1

    def test_ascii_normalized_to_utf8(self) -> None:
        result = analyze_encodings({
            "a.txt": ("ascii", 0.99),
            "b.txt": ("utf-8", 0.95),
        })
        assert result.encoding_distribution == {"utf-8": 2}

    def test_case_insensitive(self) -> None:
        result = analyze_encodings({
            "a.txt": ("UTF-8", 0.99),
            "b.txt": ("utf-8", 0.95),
        })
        assert result.encoding_distribution == {"utf-8": 2}

    def test_file_results_populated(self) -> None:
        result = analyze_encodings({"a.txt": ("utf-8", 0.99)})
        assert len(result.file_results) == 1
        assert result.file_results[0].path == "a.txt"
        assert result.file_results[0].encoding == "utf-8"
        assert result.file_results[0].confidence == 0.99


# ---------------------------------------------------------------------------
# Text cache tests
# ---------------------------------------------------------------------------


class TestBuildTextCache:
    """Test shared text cache builder."""

    def test_cache_plain_text(self, tmp_path: Path) -> None:
        (tmp_path / "hello.txt").write_text(
            "Hello world from a text file.", encoding="utf-8"
        )
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        result = build_text_cache(sample, inv, max_workers=1)
        assert result.total_extracted >= 1
        # Find the text file in the cache
        cached_texts = list(result.text_cache.values())
        assert any("Hello world" in t for t in cached_texts)
        # Encoding should be detected for plain text
        assert len(result.encoding_map) >= 1

    def test_cache_pdf(self, tmp_path: Path) -> None:
        create_pdf_with_text(
            tmp_path / "doc.pdf", "PDF content for cache test"
        )
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        result = build_text_cache(sample, inv, max_workers=1)
        cached_texts = list(result.text_cache.values())
        assert any("PDF content" in t for t in cached_texts)
        # No encoding for PDF (handled internally)
        pdf_paths = [p for p in result.text_cache if p.endswith(".pdf")]
        for p in pdf_paths:
            assert p not in result.encoding_map

    def test_cache_docx(self, tmp_path: Path) -> None:
        create_minimal_docx(
            tmp_path / "doc.docx", text="DOCX content for cache test"
        )
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        result = build_text_cache(sample, inv, max_workers=1)
        cached_texts = list(result.text_cache.values())
        assert any("DOCX content" in t for t in cached_texts)

    def test_cache_mixed_corpus(self, tmp_multilang_corpus: Path) -> None:
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_multilang_corpus, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        result = build_text_cache(sample, inv, max_workers=1)
        # Should have entries for txt, pdf, docx
        assert result.total_extracted >= 5
        assert len(result.text_cache) >= 5
        # Encoding detected for plain text files
        assert len(result.encoding_map) >= 1

    def test_cache_progress_callback(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("File A content here.", encoding="utf-8")
        (tmp_path / "b.txt").write_text("File B content here.", encoding="utf-8")
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        calls: list[tuple[int, int]] = []
        build_text_cache(
            sample, inv, max_workers=1,
            progress_callback=lambda c, t: calls.append((c, t)),
        )
        assert len(calls) >= 2

    def test_cache_corrupt_file(self, tmp_path: Path) -> None:
        # PNG bytes in a .pdf extension
        from tests.conftest import create_corrupt_pdf

        create_corrupt_pdf(tmp_path / "bad.pdf")
        (tmp_path / "good.txt").write_text("Good content.", encoding="utf-8")

        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        result = build_text_cache(sample, inv, max_workers=1)
        # Should not crash — errors counted
        assert result.total_extracted >= 1


# ---------------------------------------------------------------------------
# PII with text cache tests
# ---------------------------------------------------------------------------


class TestPiiWithTextCache:
    """Test PII scanner using pre-extracted text cache."""

    def test_pii_with_cache_detects_same(self, tmp_path: Path) -> None:
        """PII results should be identical whether using cache or not."""
        # Create file with known PII
        (tmp_path / "pii.txt").write_text(
            "Contact: john.doe@example.com\n"
            "SSN: 123-45-6789\n"
            "Normal text without PII.\n",
            encoding="utf-8",
        )
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        # Build cache
        cache_result = build_text_cache(sample, inv, max_workers=1)

        # Scan with cache
        result_cached = scan_pii(
            sample, inv, config,
            text_cache=cache_result.text_cache,
            max_workers=1,
        )

        # Scan without cache
        result_direct = scan_pii(sample, inv, config, max_workers=1)

        # Same detection results
        assert result_cached.files_with_pii == result_direct.files_with_pii
        assert result_cached.per_type_counts == result_direct.per_type_counts

    def test_pii_cache_no_crash(self, tmp_path: Path) -> None:
        """PII scan with empty cache should still work via fallback."""
        (tmp_path / "test.txt").write_text(
            "Email: test@example.com\n", encoding="utf-8"
        )
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_path, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        # Empty cache — should fall back to process pool
        result = scan_pii(sample, inv, config, text_cache={}, max_workers=1)
        assert result.total_scanned >= 1


# ---------------------------------------------------------------------------
# Integration: full pipeline test
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Test the full text cache → language → encoding pipeline."""

    def test_multilang_pipeline(self, tmp_multilang_corpus: Path) -> None:
        config = FieldCheckConfig(sampling_rate=1.0)
        walk = walk_directory(tmp_multilang_corpus, config)
        inv = analyze_inventory(walk)
        sample = select_sample(walk, inv, config)

        # Build cache
        cache_result = build_text_cache(sample, inv, max_workers=1)
        assert len(cache_result.text_cache) >= 5

        # Analyze languages
        lang_result = analyze_languages(cache_result.text_cache)
        assert lang_result.total_analyzed >= 5
        # Should detect multiple languages
        assert "English" in lang_result.language_distribution

        # Analyze encodings
        enc_result = analyze_encodings(cache_result.encoding_map)
        assert enc_result.total_analyzed >= 1
        # Most files are UTF-8
        assert "utf-8" in enc_result.encoding_distribution
