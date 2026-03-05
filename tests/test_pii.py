"""Tests for PII scanning module."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.scanner import walk_directory
from field_check.scanner.inventory import analyze_inventory
from field_check.scanner.pii import (
    BUILTIN_PATTERNS,
    PIIScanResult,
    _luhn_check,
    _scan_single_file,
    scan_pii,
)
from field_check.scanner.sampling import select_sample
from field_check.scanner.text import extract_text
from tests.conftest import create_pdf_with_text

# --- Luhn validation tests ---


class TestLuhnValidation:
    """Tests for Luhn algorithm credit card validation."""

    def test_luhn_valid_cards(self) -> None:
        """Known valid CC numbers should pass Luhn check."""
        valid_numbers = [
            "4111111111111111",  # Visa test
            "5500000000000004",  # Mastercard test
            "340000000000009",   # Amex test
            "6011000000000004",  # Discover test
        ]
        for num in valid_numbers:
            assert _luhn_check(num), f"Expected valid: {num}"

    def test_luhn_invalid_numbers(self) -> None:
        """Random digit strings should fail Luhn check."""
        for num in ["4111111111111112", "1234567890123456"]:
            assert not _luhn_check(num), f"Expected invalid: {num}"

    def test_luhn_too_short(self) -> None:
        """Numbers with fewer than 13 digits should fail."""
        assert not _luhn_check("411111111111")  # 12 digits

    def test_luhn_too_long(self) -> None:
        """Numbers with more than 19 digits should fail."""
        assert not _luhn_check("41111111111111111111")  # 20 digits

    def test_luhn_with_separators(self) -> None:
        """Luhn should handle numbers with spaces/dashes."""
        assert _luhn_check("4111 1111 1111 1111")
        assert _luhn_check("4111-1111-1111-1111")


# --- Pattern matching tests ---


class TestPatternMatching:
    """Tests for built-in PII regex patterns."""

    def _compile_pattern(self, name: str):
        """Get compiled pattern by name."""
        import re

        for p in BUILTIN_PATTERNS:
            if p["name"] == name:
                return re.compile(str(p["pattern"]))
        msg = f"Pattern {name} not found"
        raise ValueError(msg)

    def test_email_pattern_matches(self) -> None:
        """Standard email addresses should be detected."""
        pat = self._compile_pattern("email")
        assert pat.search("contact: john@example.com here")
        assert pat.search("alice.bob+tag@sub.domain.org")
        assert not pat.search("not an email at all")

    def test_ssn_pattern_matches(self) -> None:
        """XXX-XX-XXXX format should be detected."""
        pat = self._compile_pattern("ssn")
        assert pat.search("SSN: 123-45-6789")
        assert pat.search("number 987-65-4321 here")
        assert not pat.search("123456789")  # No dashes
        assert not pat.search("12-345-6789")  # Wrong grouping

    def test_phone_pattern_matches(self) -> None:
        """Various US phone formats should be detected."""
        pat = self._compile_pattern("phone")
        assert pat.search("call 555-123-4567")
        assert pat.search("(555) 123-4567")
        assert not pat.search("12345")  # Too short

    def test_ip_address_pattern_matches(self) -> None:
        """Valid IPv4 addresses should be detected."""
        pat = self._compile_pattern("ip_address")
        assert pat.search("server at 192.168.1.100")
        assert pat.search("10.0.0.1")
        assert not pat.search("999.999.999.999")  # Out of range

    def test_cc_with_luhn_validation(self) -> None:
        """Only Luhn-valid numbers should be counted as CC matches."""
        pat = self._compile_pattern("credit_card")
        # Valid Luhn number
        text = "CC: 4111 1111 1111 1111"
        match = pat.search(text)
        assert match is not None
        assert _luhn_check(match.group())

        # Invalid Luhn number
        text2 = "CC: 1234 5678 9012 3456"
        match2 = pat.search(text2)
        if match2:
            assert not _luhn_check(match2.group())


# --- Single file scanner tests ---


class TestSingleFileScanner:
    """Tests for _scan_single_file function."""

    def test_scan_text_file_with_pii(self, tmp_path: Path) -> None:
        """Text file with email should have matches."""
        import re

        f = tmp_path / "test.txt"
        f.write_text("Email: user@example.com\nNo PII line.\n", encoding="utf-8")

        patterns = [
            ("email", "Email Address", re.compile(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            ), None),
        ]
        result = _scan_single_file(str(f), "text/plain", patterns, show_samples=False)
        assert result.matches_by_type.get("email", 0) == 1
        assert len(result.sample_matches) == 0  # samples disabled

    def test_scan_clean_file_no_pii(self, tmp_path: Path) -> None:
        """Clean file should have zero matches."""
        import re

        f = tmp_path / "clean.txt"
        f.write_text("Just normal text, nothing sensitive.", encoding="utf-8")

        patterns = [
            ("email", "Email", re.compile(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            ), None),
        ]
        result = _scan_single_file(str(f), "text/plain", patterns, show_samples=False)
        assert not result.matches_by_type
        assert result.error is None

    def test_scan_with_samples_flag(self, tmp_path: Path) -> None:
        """With show_samples=True, sample_matches should be populated."""
        import re

        f = tmp_path / "emails.txt"
        f.write_text("a@b.com\nc@d.org\n", encoding="utf-8")

        patterns = [
            ("email", "Email", re.compile(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            ), None),
        ]
        result = _scan_single_file(str(f), "text/plain", patterns, show_samples=True)
        assert len(result.sample_matches) == 2
        assert result.sample_matches[0].matched_text == "a@b.com"
        assert result.sample_matches[0].line_number == 1

    def test_scan_without_samples_flag(self, tmp_path: Path) -> None:
        """Without show_samples flag, sample_matches should be empty."""
        import re

        f = tmp_path / "emails.txt"
        f.write_text("a@b.com\nc@d.org\n", encoding="utf-8")

        patterns = [
            ("email", "Email", re.compile(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            ), None),
        ]
        result = _scan_single_file(str(f), "text/plain", patterns, show_samples=False)
        assert result.matches_by_type["email"] == 2
        assert len(result.sample_matches) == 0


# --- Integration tests ---


class TestScanPiiIntegration:
    """Integration tests for scan_pii with full pipeline."""

    def _run_pipeline(
        self, corpus_path: Path, config: FieldCheckConfig | None = None
    ) -> tuple[PIIScanResult, object]:
        """Run walk → inventory → sample → PII scan pipeline."""
        cfg = config or FieldCheckConfig(sampling_rate=1.0)
        walk_result = walk_directory(corpus_path, cfg)
        inventory = analyze_inventory(walk_result)
        sample = select_sample(walk_result, inventory, cfg)
        pii_result = scan_pii(sample, inventory, cfg, max_workers=1)
        return pii_result, sample

    def test_scan_pii_detects_email_in_pdf(
        self, tmp_corpus_with_pii: Path
    ) -> None:
        """PII scanner should detect email in PDF files."""
        result, _ = self._run_pipeline(tmp_corpus_with_pii)
        assert result.total_scanned > 0
        assert result.per_type_counts.get("email", 0) >= 1

    def test_scan_pii_detects_text_file_pii(
        self, tmp_corpus_with_pii: Path
    ) -> None:
        """PII scanner should detect PII in plain text files."""
        result, _ = self._run_pipeline(tmp_corpus_with_pii)
        # contacts.txt has email + phone, data.csv has email + ssn
        assert result.per_type_counts.get("email", 0) >= 2

    def test_scan_pii_clean_file_no_pii(self, tmp_path: Path) -> None:
        """Corpus with only clean files should have zero PII matches."""
        (tmp_path / "clean.txt").write_text("No PII at all.", encoding="utf-8")
        (tmp_path / "also_clean.txt").write_text("Safe content.", encoding="utf-8")
        result, _ = self._run_pipeline(tmp_path)
        assert result.files_with_pii == 0
        assert not result.per_type_counts

    def test_scan_pii_aggregate_counts(
        self, tmp_corpus_with_pii: Path
    ) -> None:
        """Verify total_scanned and files_with_pii match expectations."""
        result, _ = self._run_pipeline(tmp_corpus_with_pii)
        # 5 files: pii_doc.pdf, clean.pdf, contacts.txt, data.csv, readme.txt
        assert result.total_scanned == 5
        # pii_doc.pdf, contacts.txt, data.csv have PII
        assert result.files_with_pii >= 2

    def test_scan_pii_show_samples_flag(
        self, tmp_corpus_with_pii: Path
    ) -> None:
        """With show_pii_samples=True, sample_matches should be populated."""
        config = FieldCheckConfig(sampling_rate=1.0, show_pii_samples=True)
        result, _ = self._run_pipeline(tmp_corpus_with_pii, config)
        all_samples = [
            m
            for fr in result.file_results
            for m in fr.sample_matches
        ]
        assert len(all_samples) > 0

    def test_scan_pii_without_samples_flag(
        self, tmp_corpus_with_pii: Path
    ) -> None:
        """Without show_pii_samples, sample_matches should be empty."""
        config = FieldCheckConfig(sampling_rate=1.0, show_pii_samples=False)
        result, _ = self._run_pipeline(tmp_corpus_with_pii, config)
        all_samples = [
            m
            for fr in result.file_results
            for m in fr.sample_matches
        ]
        assert len(all_samples) == 0


# --- Custom pattern tests ---


class TestCustomPatterns:
    """Tests for custom PII patterns from config."""

    def test_custom_pattern_from_config(self, tmp_path: Path) -> None:
        """Custom regex pattern should be detected in files."""
        (tmp_path / "ids.txt").write_text(
            "ID: AB123456C\nAnother: CD789012E\n",
            encoding="utf-8",
        )
        config = FieldCheckConfig(
            sampling_rate=1.0,
            pii_custom_patterns=[
                {"name": "UK NI Number", "pattern": r"[A-Z]{2}\d{6}[A-Z]"}
            ],
        )
        walk_result = walk_directory(tmp_path, config)
        inventory = analyze_inventory(walk_result)
        sample = select_sample(walk_result, inventory, config)
        result = scan_pii(sample, inventory, config, max_workers=1)
        assert result.per_type_counts.get("UK NI Number", 0) == 2
        assert result.pattern_labels["UK NI Number"] == "UK NI Number"


# --- Page count distribution tests ---


class TestPageCountDistribution:
    """Tests for page count tracking in text extraction."""

    def test_page_count_distribution(self, tmp_path: Path) -> None:
        """Multi-page PDF should show correct bucket."""
        create_pdf_with_text(tmp_path / "short.pdf", "Short doc", pages=1)
        create_pdf_with_text(tmp_path / "medium.pdf", "Medium doc", pages=3)
        create_pdf_with_text(tmp_path / "long.pdf", "Longer doc", pages=8)

        config = FieldCheckConfig(sampling_rate=1.0)
        walk_result = walk_directory(tmp_path, config)
        inventory = analyze_inventory(walk_result)
        sample = select_sample(walk_result, inventory, config)
        text_result = extract_text(sample, inventory)

        dist = text_result.page_count_distribution
        assert dist.get("1 page", 0) == 1
        assert dist.get("2-5 pages", 0) == 1
        assert dist.get("6-10 pages", 0) == 1

    def test_page_count_min_max(self, tmp_path: Path) -> None:
        """Verify min/max page count tracking."""
        create_pdf_with_text(tmp_path / "a.pdf", "Page A", pages=2)
        create_pdf_with_text(tmp_path / "b.pdf", "Page B", pages=5)

        config = FieldCheckConfig(sampling_rate=1.0)
        walk_result = walk_directory(tmp_path, config)
        inventory = analyze_inventory(walk_result)
        sample = select_sample(walk_result, inventory, config)
        text_result = extract_text(sample, inventory)

        assert text_result.page_count_min == 2
        assert text_result.page_count_max == 5
        assert text_result.page_count_total == 7
