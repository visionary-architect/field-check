"""Worker functions for text extraction (ProcessPoolExecutor).

These must be top-level functions in a module so they can be pickled
by ProcessPoolExecutor. Separated from text.py to keep file sizes
manageable.
"""

from __future__ import annotations

import os

from field_check.scanner.text import (
    _MAX_TEXT_READ,
    CHARS_PER_PAGE_IMAGE_HEAVY,
    CHARS_PER_PAGE_TEXT_HEAVY,
    CLASSIFICATION_IMAGE_HEAVY,
    CLASSIFICATION_MIXED,
    CLASSIFICATION_TEXT_HEAVY,
    TEXT_SIZE_RATIO_IMAGE_HEAVY,
    TextResult,
)


def _docx_full_text(doc: object) -> str:
    """Extract all text from a python-docx Document.

    Includes body paragraphs, table cells, headers, and footers.
    """
    parts: list[str] = []

    # Body paragraphs
    for p in doc.paragraphs:  # type: ignore[attr-defined]
        if p.text:
            parts.append(p.text)

    # Table cells (deduplicate merged cells by XML element identity)
    seen_cells: set[int] = set()
    for table in doc.tables:  # type: ignore[attr-defined]
        for row in table.rows:
            for cell in row.cells:
                cell_id = id(cell._tc)  # type: ignore[attr-defined]
                if cell_id not in seen_cells and cell.text:
                    seen_cells.add(cell_id)
                    parts.append(cell.text)

    # Headers and footers
    for section in doc.sections:  # type: ignore[attr-defined]
        for hf in (section.header, section.footer):
            if hf and hf.is_linked_to_previous is False:
                for p in hf.paragraphs:
                    if p.text:
                        parts.append(p.text)

    return "\n".join(parts)


def _extract_pdf(filepath: str) -> TextResult:
    """Extract text, metadata, and classification from a PDF.

    Single-pass extraction: opens the file once to get text, page count,
    scanned detection (via page.chars), content classification, and metadata.
    """
    import pdfplumber

    result = TextResult(path=filepath)
    file_size = os.path.getsize(filepath)

    try:
        with pdfplumber.open(filepath) as pdf:
            result.page_count = len(pdf.pages)

            # Extract metadata
            meta = pdf.metadata or {}
            result.metadata["title"] = meta.get("Title") or None
            result.metadata["author"] = meta.get("Author") or None
            creation = meta.get("CreationDate")
            result.metadata["creation_date"] = str(creation) if creation else None

            total_chars = 0
            total_text_bytes = 0
            scanned_pages = 0
            native_pages = 0

            page_texts: list[str] = []
            for page in pdf.pages:
                # Count char objects for scanned detection
                char_count = len(page.chars) if page.chars else 0
                if char_count == 0:
                    scanned_pages += 1
                else:
                    native_pages += 1
                    total_chars += char_count

                # Extract text
                page_text = page.extract_text() or ""
                page_texts.append(page_text)
                total_text_bytes += len(
                    page_text.encode("utf-8", errors="replace")
                )

            result.text = "\n".join(page_texts)
            result.text_length = len(result.text)

            # Scanned detection
            if result.page_count > 0:
                if scanned_pages == result.page_count:
                    result.is_scanned = True
                elif scanned_pages > 0 and native_pages > 0:
                    result.is_mixed_scan = True

            # Content classification
            if result.page_count > 0:
                result.chars_per_page = total_chars / result.page_count
                result.text_size_ratio = (
                    total_text_bytes / file_size if file_size > 0 else 0.0
                )

                if (
                    result.is_scanned
                    or result.chars_per_page < CHARS_PER_PAGE_IMAGE_HEAVY
                ):
                    result.classification = CLASSIFICATION_IMAGE_HEAVY
                elif result.chars_per_page > CHARS_PER_PAGE_TEXT_HEAVY:
                    result.classification = CLASSIFICATION_TEXT_HEAVY
                else:
                    # Mixed zone -- check secondary metric
                    if result.text_size_ratio < TEXT_SIZE_RATIO_IMAGE_HEAVY:
                        result.classification = CLASSIFICATION_IMAGE_HEAVY
                    else:
                        result.classification = CLASSIFICATION_MIXED

    except Exception as exc:
        result.error = str(exc)

    return result


def _extract_docx(filepath: str) -> TextResult:
    """Extract text and metadata from a DOCX file."""
    from docx import Document

    result = TextResult(path=filepath)
    file_size = os.path.getsize(filepath)

    try:
        doc = Document(filepath)

        # Extract text from paragraphs, tables, headers, footers
        text = _docx_full_text(doc)
        result.text = text
        text_bytes = len(text.encode("utf-8", errors="replace"))
        result.text_length = len(text)
        result.text_size_ratio = text_bytes / file_size if file_size > 0 else 0.0

        # Extract metadata
        props = doc.core_properties
        result.metadata["title"] = props.title if props.title else None
        result.metadata["author"] = props.author if props.author else None
        result.metadata["creation_date"] = (
            props.created.isoformat() if props.created else None
        )

        # DOCX is always text-based, never scanned
        result.classification = CLASSIFICATION_TEXT_HEAVY

    except Exception as exc:
        result.error = str(exc)

    return result


def _extract_single(filepath: str, mime_type: str) -> TextResult:
    """Worker function for ProcessPoolExecutor.

    Must be top-level for pickling. Dispatches to type-specific extractors.
    """
    if mime_type == "application/pdf":
        return _extract_pdf(filepath)
    elif (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return _extract_docx(filepath)
    else:
        return TextResult(path=filepath, error=f"Unsupported type: {mime_type}")


def _extract_text_for_cache(
    filepath: str, mime_type: str
) -> tuple[str, str | None, float, str | None]:
    """Worker function to extract text content from any supported file.

    Must be top-level for pickling (ProcessPoolExecutor).

    Returns:
        Tuple of (text, encoding_name, encoding_confidence, error).
        encoding_name is only set for plain text files.
    """
    try:
        if mime_type == "application/pdf":
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
            return (text, None, 0.0, None)

        if (
            mime_type
            == "application/vnd.openxmlformats-officedocument"
               ".wordprocessingml.document"
        ):
            from docx import Document

            doc = Document(filepath)
            text = _docx_full_text(doc)
            return (text, None, 0.0, None)

        # Plain text types — read bytes, detect encoding
        from charset_normalizer import from_bytes

        with open(filepath, "rb") as f:
            raw = f.read(_MAX_TEXT_READ)

        result = from_bytes(raw).best()
        if result:
            return (str(result), result.encoding, 1.0 - result.chaos, None)
        return (
            raw.decode("utf-8", errors="replace"),
            "utf-8",
            0.0,
            None,
        )
    except Exception as exc:
        return ("", None, 0.0, str(exc))


def _extract_plain_text(
    filepath: str,
) -> tuple[str, str | None, float, str | None]:
    """Extract text and encoding from a plain text file.

    Must be top-level for pickling (ProcessPoolExecutor).

    Returns:
        Tuple of (text, encoding_name, encoding_confidence, error).
    """
    try:
        from charset_normalizer import from_bytes

        with open(filepath, "rb") as f:
            raw = f.read(_MAX_TEXT_READ)

        result = from_bytes(raw).best()
        if result:
            return (str(result), result.encoding, 1.0 - result.chaos, None)
        return (raw.decode("utf-8", errors="replace"), "utf-8", 0.0, None)
    except Exception as exc:
        return ("", None, 0.0, str(exc))
