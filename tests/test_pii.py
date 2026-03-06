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
        """XXX-XX-XXXX format should be detected (valid SSA ranges only)."""
        pat = self._compile_pattern("ssn")
        assert pat.search("SSN: 123-45-6789")
        assert pat.search("number 456-78-1234 here")
        # Invalid SSN ranges must NOT match
        assert not pat.search("000-12-3456")  # Area 000 invalid
        assert not pat.search("666-12-3456")  # Area 666 invalid
        assert not pat.search("900-12-3456")  # Area 900-999 invalid
        assert not pat.search("123-00-4567")  # Group 00 invalid
        assert not pat.search("123-45-0000")  # Serial 0000 invalid
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


# --- Context scoring tests ---


class TestContextScoring:
    """Tests for context-aware PII confidence scoring."""

    def test_ssn_with_context_boost(self) -> None:
        """SSN near 'social security' should get high confidence."""
        from field_check.scanner.pii import CONTEXT_CONFIG, _compute_context_confidence

        line = "Social Security Number: 123-45-6789"
        conf = _compute_context_confidence(line, 24, 35, "ssn", CONTEXT_CONFIG)
        assert conf >= 0.6, f"Expected high confidence, got {conf}"

    def test_ssn_with_suppress_context(self) -> None:
        """SSN-like number near 'order' should get low confidence."""
        from field_check.scanner.pii import CONTEXT_CONFIG, _compute_context_confidence

        line = "Order reference: 123-45-6789"
        conf = _compute_context_confidence(line, 17, 28, "ssn", CONTEXT_CONFIG)
        assert conf <= 0.4, f"Expected low confidence, got {conf}"

    def test_ssn_no_context(self) -> None:
        """SSN-like number with no context gets base confidence."""
        from field_check.scanner.pii import CONTEXT_CONFIG, _compute_context_confidence

        line = "The value is 123-45-6789 here"
        conf = _compute_context_confidence(line, 13, 24, "ssn", CONTEXT_CONFIG)
        assert conf == 0.5  # base_confidence for SSN

    def test_phone_with_context_boost(self) -> None:
        """Phone number near 'call' should get boosted confidence."""
        from field_check.scanner.pii import CONTEXT_CONFIG, _compute_context_confidence

        line = "Please call 555-123-4567 for support"
        conf = _compute_context_confidence(line, 12, 24, "phone", CONTEXT_CONFIG)
        assert conf > 0.4  # boosted from base 0.4

    def test_min_confidence_filters(self, tmp_path: Path) -> None:
        """min_confidence > 0 should filter low-confidence matches."""
        f = tmp_path / "test.txt"
        # "order" context should suppress SSN confidence
        f.write_text(
            "Order #123-45-6789\nSSN: 456-78-1234\n", encoding="utf-8"
        )
        config_low = FieldCheckConfig(
            sampling_rate=1.0, pii_min_confidence=0.0,
        )
        config_high = FieldCheckConfig(
            sampling_rate=1.0, pii_min_confidence=0.6,
        )
        walk_result = walk_directory(tmp_path, config_low)
        inventory = analyze_inventory(walk_result)
        sample = select_sample(walk_result, inventory, config_low)

        result_low = scan_pii(sample, inventory, config_low, max_workers=1)
        result_high = scan_pii(sample, inventory, config_high, max_workers=1)

        ssn_low = result_low.per_type_counts.get("ssn", 0)
        ssn_high = result_high.per_type_counts.get("ssn", 0)
        # High confidence filter should find fewer SSN matches
        assert ssn_high <= ssn_low

    def test_unknown_pattern_gets_full_confidence(self) -> None:
        """Pattern not in CONTEXT_CONFIG should get confidence 1.0."""
        from field_check.scanner.pii import CONTEXT_CONFIG, _compute_context_confidence

        line = "Custom pattern match here"
        conf = _compute_context_confidence(
            line, 0, 10, "unknown_pattern", CONTEXT_CONFIG
        )
        assert conf == 1.0

    def test_confidence_in_sample_matches(self, tmp_path: Path) -> None:
        """PIIMatch should include confidence when show_pii_samples=True."""
        f = tmp_path / "test.txt"
        f.write_text("Email: user@example.com\n", encoding="utf-8")
        config = FieldCheckConfig(
            sampling_rate=1.0, show_pii_samples=True,
        )
        walk_result = walk_directory(tmp_path, config)
        inventory = analyze_inventory(walk_result)
        sample = select_sample(walk_result, inventory, config)
        result = scan_pii(sample, inventory, config, max_workers=1)

        matches = [
            m for fr in result.file_results for m in fr.sample_matches
        ]
        assert len(matches) >= 1
        assert matches[0].confidence > 0


# --- Phone validation tests ---


class TestPhoneValidation:
    """Tests for phone number validation with phonenumberslite."""

    def test_validate_phone_valid_us(self) -> None:
        """Valid US phone numbers should pass validation."""
        from field_check.scanner.pii import _validate_phone

        # Standard US numbers with valid area codes
        assert _validate_phone("+1 212-555-1234")
        assert _validate_phone("(212) 555-1234")

    def test_validate_phone_invalid_area_code(self) -> None:
        """Invalid area codes should fail (when phonenumberslite installed)."""
        from field_check.scanner.pii import _validate_phone

        # Try to import; if not installed, test is a no-op
        try:
            import phonenumbers  # noqa: F401

            # 000 is not a valid area code
            assert not _validate_phone("000-555-1234")
        except ImportError:
            pass  # Graceful: can't test without library

    def test_validate_phone_graceful_fallback(self) -> None:
        """Without phonenumberslite, _validate_phone accepts all."""
        from unittest.mock import patch

        from field_check.scanner.pii import _validate_phone

        with patch.dict("sys.modules", {"phonenumbers": None}):
            # Should return True (accept all) when import fails
            result = _validate_phone("000-000-0000")
            assert result is True

    def test_invalid_phone_gets_low_confidence(self, tmp_path: Path) -> None:
        """Invalid phone numbers should have confidence capped at 0.1."""
        try:
            import phonenumbers  # noqa: F401
        except ImportError:
            import pytest

            pytest.skip("phonenumberslite not installed")

        import re

        from field_check.scanner.pii import CONTEXT_CONFIG, _scan_text_for_pii

        patterns = [
            ("phone", "Phone Number", re.compile(
                r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)"
                r"\d{3}[-.\s]?\d{4}\b"
            ), None),
        ]
        # 000 is not a valid area code
        text = "Phone: 000-555-1234\n"
        result = _scan_text_for_pii(
            "fake.txt", text, patterns, show_samples=True,
            context_config=CONTEXT_CONFIG, min_confidence=0.0,
        )
        if result.sample_matches:
            assert result.sample_matches[0].confidence <= 0.1


class TestContextScoringFixes:
    """Tests for whole-word matching, proximity weighting, and SSN exclusions."""

    def test_whole_word_matching_no_substring_suppress(self):
        """Substring 'lic' inside 'duplicate' should NOT suppress."""
        from field_check.scanner.pii_helpers import compute_context_confidence

        # "order" should suppress, but "duplicate" should NOT
        # (even though it contains "lic" as a substring)
        ctx = {"ssn": (0.5, [], ["order", "lic"])}
        line = "duplicate entry 123-45-6789 found"
        conf = compute_context_confidence(line, 16, 27, "ssn", ctx)
        # "lic" is NOT a whole word in "duplicate", so no suppression
        assert conf == 0.5  # base confidence, no change

    def test_whole_word_matching_actual_word_suppresses(self):
        """Actual whole-word match should suppress."""
        from field_check.scanner.pii_helpers import compute_context_confidence

        ctx = {"ssn": (0.5, [], ["order"])}
        line = "order number 123-45-6789"
        conf = compute_context_confidence(line, 13, 24, "ssn", ctx)
        assert conf < 0.5  # should be suppressed

    def test_proximity_weighting_closer_words_score_higher(self):
        """Words closer to the match should produce higher boost."""
        from field_check.scanner.pii_helpers import compute_context_confidence

        ctx = {"ssn": (0.5, ["ssn"], [])}
        # Close context: "ssn" right before match
        line_close = "ssn 123-45-6789"
        conf_close = compute_context_confidence(line_close, 4, 15, "ssn", ctx)

        # Far context: "ssn" far from match
        line_far = "ssn " + ("x" * 80) + " 123-45-6789"
        conf_far = compute_context_confidence(line_far, 84, 95, "ssn", ctx)

        assert conf_close > conf_far

    def test_known_test_ssn_excluded(self):
        """Known test SSNs (Woolworth's) should be excluded."""
        import re

        from field_check.scanner.pii_helpers import scan_text_for_pii

        patterns = [
            ("ssn", "SSN (US)", re.compile(
                r"(?<![#\w])(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\w)"
            ), None),
        ]
        text = "SSN: 078-05-1120\n"  # Woolworth's wallet SSN
        result = scan_text_for_pii(
            "fake.txt", text, patterns, show_samples=True,
        )
        assert result.matches_by_type.get("ssn", 0) == 0

    def test_negative_lookbehind_hash_prefix(self):
        """SSN pattern should not match after # prefix."""
        import re

        from field_check.scanner.pii import BUILTIN_PATTERNS

        ssn_pattern = None
        for p in BUILTIN_PATTERNS:
            if p["name"] == "ssn":
                ssn_pattern = re.compile(str(p["pattern"]))
                break

        assert ssn_pattern is not None
        # Should NOT match: preceded by #
        assert ssn_pattern.search("Order #123-45-6789") is None
        # Should match: normal context
        assert ssn_pattern.search("SSN 123-45-6789") is not None

    def test_valid_ssn_still_matches(self):
        """Valid SSNs without # prefix should still be detected."""
        import re

        from field_check.scanner.pii_helpers import scan_text_for_pii

        patterns = [
            ("ssn", "SSN (US)", re.compile(
                r"(?<![#\w])(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\w)"
            ), None),
        ]
        text = "Social security 123-45-6789\n"
        result = scan_text_for_pii(
            "fake.txt", text, patterns, show_samples=True,
        )
        assert result.matches_by_type.get("ssn", 0) == 1


class TestInternationalPII:
    """Tests for international PII patterns (IBAN, UK NINO, DE Tax ID, ES DNI)."""

    def test_valid_iban_detected(self):
        """Valid IBAN should be detected."""
        import re

        from field_check.scanner.pii_helpers import scan_text_for_pii

        patterns = [
            ("iban", "IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "iban"),
        ]
        # DE89370400440532013000 is a known valid German IBAN
        text = "IBAN: DE89370400440532013000\n"
        result = scan_text_for_pii("fake.txt", text, patterns, show_samples=True)
        assert result.matches_by_type.get("iban", 0) == 1

    def test_invalid_iban_rejected(self):
        """IBAN with invalid check digits should be rejected."""
        import re

        from field_check.scanner.pii_helpers import scan_text_for_pii

        patterns = [
            ("iban", "IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "iban"),
        ]
        # Invalid check digits
        text = "IBAN: DE00370400440532013000\n"
        result = scan_text_for_pii("fake.txt", text, patterns, show_samples=True)
        assert result.matches_by_type.get("iban", 0) == 0

    def test_uk_nino_pattern_matches(self):
        """Valid UK NINO format should be detected."""
        import re

        from field_check.scanner.pii_helpers import scan_text_for_pii

        patterns = [
            ("uk_nino", "UK NINO",
             re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"), None),
        ]
        text = "NI Number: AB123456C\n"
        result = scan_text_for_pii("fake.txt", text, patterns, show_samples=True)
        assert result.matches_by_type.get("uk_nino", 0) == 1

    def test_uk_nino_invalid_prefix_rejected(self):
        """UK NINO with invalid prefix letters should not match."""
        import re

        pattern = re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")
        # D and F are excluded prefixes
        assert pattern.search("DF123456A") is None

    def test_de_tax_id_valid(self):
        """Valid German Tax ID should pass validation."""
        from field_check.scanner.pii_helpers import validate_de_tax_id

        try:
            from stdnum.de import idnr  # noqa: F401
            # 86095742719 passes check digit validation
            assert validate_de_tax_id("86095742719") is True
        except ImportError:
            # Without stdnum, all pass (graceful)
            assert validate_de_tax_id("12345678901") is True

    def test_de_tax_id_invalid(self):
        """Invalid German Tax ID should fail validation."""
        from field_check.scanner.pii_helpers import validate_de_tax_id

        try:
            from stdnum.de import idnr  # noqa: F401
            assert validate_de_tax_id("00000000000") is False
        except ImportError:
            pass  # Can't test without library

    def test_es_dni_valid(self):
        """Valid Spanish DNI should pass validation."""
        from field_check.scanner.pii_helpers import validate_es_dni

        try:
            from stdnum.es import dni  # noqa: F401
            # 12345678Z is a known valid DNI
            assert validate_es_dni("12345678Z") is True
        except ImportError:
            assert validate_es_dni("12345678Z") is True

    def test_es_dni_invalid_letter(self):
        """Spanish DNI with wrong check letter should fail."""
        from field_check.scanner.pii_helpers import validate_es_dni

        try:
            from stdnum.es import dni  # noqa: F401
            # Wrong letter for this number
            assert validate_es_dni("12345678A") is False
        except ImportError:
            pass  # Can't test without library

    def test_validate_iban_fallback_mod97(self):
        """IBAN validation should work with Mod-97 fallback."""
        from unittest.mock import patch

        from field_check.scanner.pii_helpers import validate_iban

        with patch.dict("sys.modules", {"stdnum": None, "stdnum.iban": None}):
            # Valid IBAN should pass Mod-97
            assert validate_iban("GB29NWBK60161331926819") is True
            # Short string should fail
            assert validate_iban("GB00") is False

    def test_international_patterns_in_builtin(self):
        """All international patterns should be in BUILTIN_PATTERNS."""
        from field_check.scanner.pii import BUILTIN_PATTERNS

        names = {str(p["name"]) for p in BUILTIN_PATTERNS}
        assert "iban" in names
        assert "uk_nino" in names
        assert "de_tax_id" in names
        assert "es_dni" in names
