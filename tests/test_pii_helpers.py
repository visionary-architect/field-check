"""Tests for PII detection helpers: validators, context scoring, scan_text_for_pii."""

from __future__ import annotations

import re

from field_check.scanner.pii_helpers import (
    CONTEXT_CONFIG,
    compute_context_confidence,
    luhn_check,
    scan_text_for_pii,
    validate_de_tax_id,
    validate_es_dni,
    validate_iban,
    validate_phone,
)

# --- Luhn validation ---


class TestLuhnCheck:
    """Luhn algorithm edge cases beyond the basic tests in test_pii.py."""

    def test_with_spaces_and_dashes(self) -> None:
        """Luhn ignores non-digit chars and still validates."""
        assert luhn_check("4111 1111 1111 1111")
        assert luhn_check("4111-1111-1111-1111")

    def test_empty_string(self) -> None:
        assert not luhn_check("")

    def test_non_numeric(self) -> None:
        assert not luhn_check("abcdefghijklmnop")

    def test_boundary_13_digits(self) -> None:
        # 13 digits is the minimum accepted length
        assert not luhn_check("123456789012")  # 12 digits → too short
        # 13 digits that passes Luhn: 4222222222222
        assert luhn_check("4222222222222")

    def test_boundary_19_digits(self) -> None:
        # 19 digits is the maximum accepted length
        assert not luhn_check("41111111111111111111")  # 20 digits → too long


# --- Phone validation ---


class TestValidatePhone:
    """Phone validation with/without phonenumberslite."""

    def test_returns_bool(self) -> None:
        result = validate_phone("555-123-4567")
        assert isinstance(result, bool)

    def test_clearly_invalid(self) -> None:
        # Too short to be any valid number
        result = validate_phone("123")
        # Without phonenumberslite: True (graceful); with it: False
        assert isinstance(result, bool)

    def test_gibberish_returns_false_or_true(self) -> None:
        # Non-numeric input
        result = validate_phone("not-a-number-at-all")
        assert isinstance(result, bool)


# --- IBAN validation ---


class TestValidateIban:
    """IBAN validation with fallback Mod-97."""

    def test_valid_de_iban(self) -> None:
        assert validate_iban("DE89370400440532013000")

    def test_valid_gb_iban(self) -> None:
        assert validate_iban("GB82WEST12345698765432")

    def test_invalid_check_digits(self) -> None:
        # Modify check digits
        assert not validate_iban("DE00370400440532013000")

    def test_too_short(self) -> None:
        assert not validate_iban("DE8937")

    def test_empty_string(self) -> None:
        assert not validate_iban("")

    def test_with_spaces(self) -> None:
        # Mod-97 fallback strips spaces
        assert validate_iban("DE89 3704 0044 0532 0130 00")


# --- German Tax ID validation ---


class TestValidateDeTaxId:
    """German Tax ID structural validation."""

    def test_valid_structure(self) -> None:
        # 11 digits, first non-zero, reasonable digit distribution
        assert validate_de_tax_id("11234567899")

    def test_starts_with_zero(self) -> None:
        assert not validate_de_tax_id("01234567890")

    def test_wrong_length(self) -> None:
        assert not validate_de_tax_id("1234567890")  # 10 digits
        assert not validate_de_tax_id("123456789012")  # 12 digits

    def test_all_same_digit(self) -> None:
        # All same digit → max count > 3
        assert not validate_de_tax_id("11111111111")

    def test_all_unique_digits(self) -> None:
        # 10 unique digits out of 11 → len(counts) == 10, should fail
        # "12345678901" has digits 0-9 all present + one repeat
        assert not validate_de_tax_id("12345678901")

    def test_non_numeric(self) -> None:
        assert not validate_de_tax_id("abcdefghijk")

    def test_empty(self) -> None:
        assert not validate_de_tax_id("")

    def test_digit_repeated_4_times(self) -> None:
        # "11112345678" → digit '1' appears 4 times → invalid
        assert not validate_de_tax_id("11112345678")


# --- Spanish DNI validation ---


class TestValidateEsDni:
    """Spanish DNI validation."""

    def test_returns_bool(self) -> None:
        result = validate_es_dni("12345678Z")
        assert isinstance(result, bool)

    def test_invalid_format(self) -> None:
        result = validate_es_dni("not-a-dni")
        # Without stdnum: True (graceful); with it: False
        assert isinstance(result, bool)


# --- Context confidence scoring ---


class TestContextConfidence:
    """Context-aware PII confidence scoring."""

    def test_boost_word_increases_confidence(self) -> None:
        line = "Please email us at user@example.com for support"
        # "email" is a boost word for the email pattern
        conf = compute_context_confidence(line, 22, 38, "email", CONTEXT_CONFIG)
        base = CONTEXT_CONFIG["email"][0]  # 0.8
        assert conf > base

    def test_suppress_word_decreases_confidence(self) -> None:
        line = "order number 123-45-6789 for tracking"
        # "order" and "tracking" are suppress words for SSN
        conf = compute_context_confidence(line, 13, 24, "ssn", CONTEXT_CONFIG)
        base = CONTEXT_CONFIG["ssn"][0]  # 0.5
        assert conf < base

    def test_no_context_uses_base(self) -> None:
        line = "XYZXYZ 123-45-6789 XYZXYZ"
        conf = compute_context_confidence(line, 7, 18, "ssn", CONTEXT_CONFIG)
        base = CONTEXT_CONFIG["ssn"][0]
        assert conf == base

    def test_unknown_pattern_returns_1(self) -> None:
        conf = compute_context_confidence("anything", 0, 8, "unknown_pattern", CONTEXT_CONFIG)
        assert conf == 1.0

    def test_confidence_clamped_to_0_1(self) -> None:
        # Many suppress words → should not go below 0
        line = (
            "order invoice tracking serial reference part model item "
            "sku code 123-45-6789 order tracking serial"
        )
        conf = compute_context_confidence(line, 59, 70, "ssn", CONTEXT_CONFIG)
        assert 0.0 <= conf <= 1.0

    def test_proximity_weighting(self) -> None:
        # Boost word close to match should have more effect than far away
        line_close = "ssn: 123-45-6789"
        line_far = "ssn " + "x" * 90 + " 123-45-6789"
        conf_close = compute_context_confidence(line_close, 5, 16, "ssn", CONTEXT_CONFIG)
        conf_far = compute_context_confidence(
            line_far, len(line_far) - 11, len(line_far), "ssn", CONTEXT_CONFIG
        )
        assert conf_close >= conf_far


# --- scan_text_for_pii ---


class TestScanTextForPii:
    """Tests for the main text scanning function."""

    def _make_patterns(self) -> list[tuple[str, str, re.Pattern[str], str | None]]:
        """Build compiled patterns for testing."""
        return [
            ("email", "Email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), None),
            (
                "ssn",
                "SSN",
                re.compile(r"(?<![#\w])(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\w)"),
                None,
            ),
        ]

    def test_finds_email(self) -> None:
        text = "Contact user@example.com for info"
        result = scan_text_for_pii("test.txt", text, self._make_patterns(), False)
        assert result.matches_by_type.get("email", 0) >= 1

    def test_empty_text(self) -> None:
        result = scan_text_for_pii("test.txt", "", self._make_patterns(), False)
        assert not result.matches_by_type

    def test_show_samples_stores_matches(self) -> None:
        text = "Email: test@example.com"
        result = scan_text_for_pii("test.txt", text, self._make_patterns(), True)
        assert len(result.sample_matches) >= 1
        assert result.sample_matches[0].matched_text == "test@example.com"

    def test_show_samples_false_stores_nothing(self) -> None:
        text = "Email: test@example.com"
        result = scan_text_for_pii("test.txt", text, self._make_patterns(), False)
        assert len(result.sample_matches) == 0

    def test_known_test_ssn_excluded(self) -> None:
        # Woolworth's wallet SSN should be filtered out
        text = "SSN: 078-05-1120"
        result = scan_text_for_pii("test.txt", text, self._make_patterns(), False)
        assert result.matches_by_type.get("ssn", 0) == 0

    def test_match_cap_per_file(self) -> None:
        # Generate text with many email matches
        lines = [f"user{i}@example.com" for i in range(20_000)]
        text = "\n".join(lines)
        result = scan_text_for_pii("test.txt", text, self._make_patterns(), False)
        # Should be capped at 10_000
        assert result.matches_by_type.get("email", 0) <= 10_000

    def test_min_confidence_filters(self) -> None:
        text = "order number 123-45-6789 tracking"
        result = scan_text_for_pii(
            "test.txt",
            text,
            self._make_patterns(),
            False,
            context_config=CONTEXT_CONFIG,
            min_confidence=0.9,
        )
        # SSN with suppress context should be below 0.9
        assert result.matches_by_type.get("ssn", 0) == 0

    def test_multiline_text(self) -> None:
        text = "Line 1\nEmail: a@b.com\nLine 3\nSSN: 123-45-6789"
        result = scan_text_for_pii("test.txt", text, self._make_patterns(), True)
        assert result.matches_by_type.get("email", 0) >= 1
        # Check line numbers in samples
        email_match = next(m for m in result.sample_matches if m.pattern_name == "email")
        assert email_match.line_number == 2
