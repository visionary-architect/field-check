"""PII detection helpers: context scoring, phone validation, and Luhn check."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from field_check.scanner.pii import PIIFileResult

# Context scoring — (base_confidence, boost_words, suppress_words)
# Inspired by Microsoft Presidio's context-aware scoring approach.
# Fixed in 2026: uses whole-word matching (not substring) per Presidio v2.2.361.
_CONTEXT_WINDOW = 100  # chars before/after match to scan for context

# Known test/invalid SSNs that should always be excluded
_KNOWN_TEST_SSNS: set[str] = {
    "078051120",  # Woolworth's wallet SSN (used in ads, 1938)
    "219099999",  # SSA advertising SSN
}

CONTEXT_CONFIG: dict[str, tuple[float, list[str], list[str]]] = {
    "email": (
        0.8,
        ["email", "e-mail", "contact", "mailto"],
        [],
    ),
    "credit_card": (
        0.7,
        ["card", "credit", "payment", "billing", "visa", "mastercard"],
        ["order", "tracking", "serial", "reference"],
    ),
    "ssn": (
        0.5,
        ["social security", "ssn", "taxpayer", "tax id", "social sec"],
        [
            "order",
            "invoice",
            "tracking",
            "serial",
            "reference",
            "part",
            "model",
            "item",
            "sku",
            "code",
        ],
    ),
    "phone": (
        0.4,
        ["phone", "call", "tel", "mobile", "cell", "fax", "contact"],
        ["order", "item", "sku", "zip", "postal", "code", "part"],
    ),
    "ip_address": (
        0.6,
        ["ip", "host", "server", "network", "address", "dns"],
        ["version"],
    ),
    "iban": (
        0.6,
        ["iban", "bank", "account", "transfer", "payment", "swift", "bic"],
        ["serial", "reference", "order", "tracking"],
    ),
    "uk_nino": (
        0.5,
        ["national insurance", "nino", "ni number", "tax", "hmrc"],
        ["serial", "reference", "order", "model"],
    ),
    "de_tax_id": (
        0.3,
        ["steuer", "tax", "finanzamt", "identifikationsnummer", "idnr"],
        ["phone", "zip", "postal", "order", "serial", "isbn"],
    ),
    "es_dni": (
        0.5,
        ["dni", "documento", "identidad", "nie", "nif"],
        ["order", "reference", "serial", "code", "postal"],
    ),
}


def luhn_check(number_str: str) -> bool:
    """Validate a number string using the Luhn algorithm.

    Args:
        number_str: String potentially containing a credit card number.

    Returns:
        True if the digits pass the Luhn checksum.
    """
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def validate_phone(number_str: str) -> bool:
    """Validate a phone number using phonenumberslite (if installed).

    Returns True if the number is structurally valid, or if
    phonenumberslite is not installed (graceful degradation).
    """
    try:
        import phonenumbers

        parsed = phonenumbers.parse(number_str, "US")
        return phonenumbers.is_valid_number(parsed)
    except ImportError:
        return True  # Accept all matches without the library
    except Exception:
        return False  # Parse failure = likely not a real number


def validate_iban(iban_str: str) -> bool:
    """Validate an IBAN using python-stdnum (if installed), else Mod-97.

    Returns True if the IBAN passes check digit validation.
    """
    try:
        from stdnum import iban

        return iban.is_valid(iban_str)
    except ImportError:
        # Fallback: basic Mod-97 check (ISO 7064)
        clean = iban_str.replace(" ", "").upper()
        if len(clean) < 15:
            return False
        rearranged = clean[4:] + clean[:4]
        numeric = ""
        for ch in rearranged:
            if ch.isdigit():
                numeric += ch
            else:
                numeric += str(ord(ch) - ord("A") + 10)
        return int(numeric) % 97 == 1
    except Exception:
        return False


def validate_de_tax_id(tax_id_str: str) -> bool:
    """Validate a German Tax ID (Steuer-IdNr) using python-stdnum.

    Returns True if valid, or True if stdnum is not installed (graceful).
    """
    try:
        from stdnum.de import idnr

        return idnr.is_valid(tax_id_str)
    except ImportError:
        return True  # Accept without library
    except Exception:
        return False


def validate_es_dni(dni_str: str) -> bool:
    """Validate a Spanish DNI using python-stdnum.

    Returns True if valid, or True if stdnum is not installed (graceful).
    """
    try:
        from stdnum.es import dni

        return dni.is_valid(dni_str)
    except ImportError:
        return True  # Accept without library
    except Exception:
        return False


def compute_context_confidence(
    line: str,
    match_start: int,
    match_end: int,
    pattern_name: str,
    context_config: dict[str, tuple[float, list[str], list[str]]],
) -> float:
    """Score match confidence based on surrounding context words.

    Checks a window around the match for boost words (increase confidence)
    and suppress words (decrease confidence).

    Args:
        line: Full text line containing the match.
        match_start: Start index of the match in the line.
        match_end: End index of the match in the line.
        pattern_name: Name of the matched pattern.
        context_config: Dict of pattern_name -> (base, boost, suppress).

    Returns:
        Confidence score clamped to [0.0, 1.0].
    """
    cfg = context_config.get(pattern_name)
    if cfg is None:
        return 1.0

    base, boost_words, suppress_words = cfg
    confidence = base

    # Build context window (text before + after the match, lowercased)
    window_start = max(0, match_start - _CONTEXT_WINDOW)
    window_end = min(len(line), match_end + _CONTEXT_WINDOW)
    before_text = line[window_start:match_start].lower()
    after_text = line[match_end:window_end].lower()
    context = before_text + " " + after_text

    match_center = (match_start + match_end) / 2

    # Boost: +0.15 per keyword found (proximity-weighted), max +0.4
    # Uses whole-word matching to avoid substring false matches
    # (e.g., "lic" should not match inside "duplicate")
    boost = 0.0
    for word in boost_words:
        match_obj = re.search(r"\b" + re.escape(word) + r"\b", context)
        if match_obj:
            # Proximity weight: closer words get higher weight
            word_pos = window_start + match_obj.start()
            distance = abs(word_pos - match_center)
            weight = max(0.2, 1.0 - distance / _CONTEXT_WINDOW)
            boost += 0.15 * weight
    confidence += min(boost, 0.4)

    # Suppress: -0.2 per keyword found (proximity-weighted), max -0.4
    suppress = 0.0
    for word in suppress_words:
        match_obj = re.search(r"\b" + re.escape(word) + r"\b", context)
        if match_obj:
            word_pos = window_start + match_obj.start()
            distance = abs(word_pos - match_center)
            weight = max(0.2, 1.0 - distance / _CONTEXT_WINDOW)
            suppress += 0.2 * weight
    confidence -= min(suppress, 0.4)

    return max(0.0, min(1.0, confidence))


def scan_text_for_pii(
    filepath: str,
    text: str,
    compiled_patterns: list[tuple[str, str, re.Pattern[str], str | None]],
    show_samples: bool,
    context_config: dict[str, tuple[float, list[str], list[str]]] | None = None,
    min_confidence: float = 0.0,
) -> PIIFileResult:
    """Scan pre-extracted text for PII patterns (no file I/O).

    Used when text is available from the shared text cache.

    Args:
        filepath: Path to the file (for result metadata).
        text: Pre-extracted text content.
        compiled_patterns: List of (name, label, pattern, validator) tuples.
        show_samples: Whether to store matched content.
        context_config: Context scoring config per pattern name.
        min_confidence: Minimum confidence to count a match.

    Returns:
        PII scan result for this file.
    """
    from field_check.scanner.pii import PIIFileResult, PIIMatch

    file_result = PIIFileResult(path=filepath)
    if not text:
        return file_result

    ctx = context_config or {}

    for line_num, line in enumerate(text.split("\n"), 1):
        for name, _label, pattern, validator in compiled_patterns:
            for match in pattern.finditer(line):
                matched = match.group()
                if validator == "luhn" and not luhn_check(matched):
                    continue
                if validator == "iban" and not validate_iban(matched):
                    continue
                if validator == "de_tax_id" and not validate_de_tax_id(matched):
                    continue
                if validator == "es_dni" and not validate_es_dni(matched):
                    continue
                # Exclude known test SSNs
                if name == "ssn":
                    digits = "".join(c for c in matched if c.isdigit())
                    if digits in _KNOWN_TEST_SSNS:
                        continue
                conf = compute_context_confidence(line, match.start(), match.end(), name, ctx)
                # Phone validation: invalid numbers get heavily penalized
                if name == "phone" and not validate_phone(matched):
                    conf = min(conf, 0.1)
                if conf < min_confidence:
                    continue
                file_result.matches_by_type[name] = file_result.matches_by_type.get(name, 0) + 1
                if show_samples and len(file_result.sample_matches) < 5:
                    file_result.sample_matches.append(
                        PIIMatch(
                            pattern_name=name,
                            matched_text=matched,
                            line_number=line_num,
                            confidence=conf,
                        )
                    )

    return file_result
