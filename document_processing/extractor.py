"""
PDF text extraction layer for Sovereign Executive.

Responsibilities:
    PDF -> page-aware text

This module does NOT:
    - extract invoice fields
    - calculate totals
    - calculate taxes
    - compare invoices
    - interpret contract clauses

Those responsibilities belong to parser.py, comparator.py,
and contract_terms.py.

Features:
    1. Page-by-page extraction
    2. Reading-order aware text extraction
    3. OCR fallback for scanned/image-only pages
    4. Text cleanup while preserving useful line structure
    5. Page numbers preserved for contract evidence/citations
    6. Extraction warnings and metadata
    7. Handles empty/partially readable PDFs
    8. Uses modern PyMuPDF API
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------

try:
    import pymupdf
except ImportError:
    pymupdf = None


try:
    from PIL import Image
except ImportError:
    Image = None


try:
    import pytesseract
except ImportError:
    pytesseract = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MIN_TEXT_CHARS = 30
DEFAULT_OCR_DPI = 200


# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

def _require_pymupdf():
    if pymupdf is None:
        raise ImportError(
            "PyMuPDF is required for PDF extraction.\n"
            "Install it with:\n"
            "    pip install pymupdf"
        )


def _ocr_available() -> bool:
    return Image is not None and pytesseract is not None


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """
    Clean extracted/OCR text without destroying line boundaries.

    Important:
        The parser and contract parser rely on line structure, so we do NOT
        collapse the entire document into one line.
    """

    if not text:
        return ""

    # Normalize different newline styles.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Replace non-breaking spaces.
    text = text.replace("\xa0", " ")

    # Remove null/control characters while preserving tabs/newlines.
    text = "".join(
        ch
        for ch in text
        if ch == "\n" or ch == "\t" or ch >= " "
    )

    # Normalize horizontal whitespace.
    text = re.sub(r"[ \t]+", " ", text)

    # Remove whitespace-only lines.
    lines = []
    for line in text.split("\n"):
        line = line.strip()

        if not line:
            continue

        lines.append(line)

    return "\n".join(lines).strip()


def _looks_like_real_text(text: str, min_chars: int) -> bool:
    """
    Decide whether a page has enough machine-readable text.

    We don't simply check len(text), because a page containing a few
    accidental characters should still be considered OCR-worthy.
    """

    if not text:
        return False

    cleaned = text.strip()

    if len(cleaned) < min_chars:
        return False

    # Require at least some alphabetic/numeric content.
    meaningful = re.findall(r"[A-Za-z0-9]", cleaned)

    return len(meaningful) >= 10


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def _ocr_page(
    page,
    dpi: int = DEFAULT_OCR_DPI,
    language: str = "eng",
) -> str:
    """
    Render one PDF page to an image and OCR it.

    Returns:
        OCR text, or an empty string if OCR cannot be performed.
    """

    if not _ocr_available():
        return ""

    try:
        zoom = dpi / 72.0

        matrix = pymupdf.Matrix(zoom, zoom)

        pixmap = page.get_pixmap(
            matrix=matrix,
            alpha=False,
        )

        image_bytes = pixmap.tobytes("png")

        image = Image.open(io.BytesIO(image_bytes))

        text = pytesseract.image_to_string(
            image,
            lang=language,
            config="--psm 6",
        )

        return _clean_text(text)

    except Exception:
        # OCR is a fallback. A failure here should not crash extraction of
        # pages that already contain normal PDF text.
        return ""


# ---------------------------------------------------------------------------
# Single page extraction
# ---------------------------------------------------------------------------

def _extract_page(
    page,
    page_number: int,
    use_ocr: bool,
    ocr_dpi: int,
    ocr_lang: str,
    min_text_chars: int,
) -> Dict[str, Any]:
    """
    Extract one page.

    Output intentionally contains at least:
        page
        text

    because parser.py and contract_terms.py depend on those fields.
    """

    warnings: List[str] = []

    # sort=True generally gives more natural reading order for PDFs where
    # text objects were stored in a strange internal order.
    try:
        raw_text = page.get_text("text", sort=True)
    except TypeError:
        # Compatibility fallback for PyMuPDF versions that don't support
        # sort in this form.
        raw_text = page.get_text("text")

    text = _clean_text(raw_text)

    ocr_used = False

    # -----------------------------------------------------------------------
    # OCR fallback
    # -----------------------------------------------------------------------

    if not _looks_like_real_text(text, min_text_chars):

        if use_ocr:
            if not _ocr_available():
                warnings.append(
                    "Page has little/no extractable text and OCR dependencies "
                    "are not installed."
                )
            else:
                ocr_text = _ocr_page(
                    page,
                    dpi=ocr_dpi,
                    language=ocr_lang,
                )

                if _looks_like_real_text(ocr_text, min_text_chars):
                    text = ocr_text
                    ocr_used = True
                else:
                    warnings.append(
                        "Page contains little/no readable text and OCR "
                        "could not recover sufficient text."
                    )
        else:
            warnings.append(
                "Page contains little/no machine-readable text; OCR disabled."
            )

    if not text:
        warnings.append("No text could be extracted from this page.")

    return {
        "page": page_number,
        "text": text,
        "ocr_used": ocr_used,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def extract_pdf_text(
    file_path,
    use_ocr: bool = True,
    ocr_dpi: int = DEFAULT_OCR_DPI,
    ocr_lang: str = "eng",
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
) -> List[Dict[str, Any]]:
    """
    Extract a PDF page-by-page.

    Parameters
    ----------
    file_path:
        Path to the PDF.

    use_ocr:
        If True, pages with insufficient machine-readable text are passed
        through OCR.

    ocr_dpi:
        Resolution used when rendering pages for OCR.

    ocr_lang:
        Tesseract language, normally "eng".

    min_text_chars:
        Minimum amount of useful text expected before OCR is triggered.

    Returns
    -------
    list[dict]

    Example:
        [
            {
                "page": 1,
                "text": "BluePeak IT Services Pvt Ltd\\nInvoice No...",
                "ocr_used": False,
                "warnings": []
            },
            {
                "page": 2,
                "text": "...",
                "ocr_used": True,
                "warnings": []
            }
        ]

    The important compatibility contract for downstream modules is:

        result[i]["page"]
        result[i]["text"]
    """

    _require_pymupdf()

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"PDF file not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Expected a PDF file but received: {path}"
        )

    if path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a PDF file, got: {path.suffix or 'unknown extension'}"
        )

    pages: List[Dict[str, Any]] = []

    document = None

    try:
        document = pymupdf.open(str(path))

        if document.page_count == 0:
            raise ValueError(
                f"PDF contains no pages: {path.name}"
            )

        for page_index in range(document.page_count):

            page = document.load_page(page_index)

            page_data = _extract_page(
                page=page,
                page_number=page_index + 1,
                use_ocr=use_ocr,
                ocr_dpi=ocr_dpi,
                ocr_lang=ocr_lang,
                min_text_chars=min_text_chars,
            )

            pages.append(page_data)

    except Exception as exc:

        if isinstance(exc, (FileNotFoundError, ValueError)):
            raise

        raise RuntimeError(
            f"Failed to extract PDF '{path.name}': {exc}"
        ) from exc

    finally:

        if document is not None:
            document.close()

    return pages


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def extract_full_text(
    file_path,
    use_ocr: bool = True,
    ocr_dpi: int = DEFAULT_OCR_DPI,
    ocr_lang: str = "eng",
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
) -> str:
    """
    Return the complete document as one string.

    This is a convenience function for code that doesn't need page
    information.

    Page-aware extraction should still use extract_pdf_text().
    """

    pages = extract_pdf_text(
        file_path=file_path,
        use_ocr=use_ocr,
        ocr_dpi=ocr_dpi,
        ocr_lang=ocr_lang,
        min_text_chars=min_text_chars,
    )

    return "\n\n".join(
        page["text"]
        for page in pages
        if page.get("text")
    )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def extraction_summary(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Produce a small diagnostic summary.

    Useful for Streamlit/debugging but not required by parser.py.
    """

    total_pages = len(pages)

    pages_with_text = sum(
        bool(page.get("text", "").strip())
        for page in pages
    )

    ocr_pages = sum(
        bool(page.get("ocr_used"))
        for page in pages
    )

    warnings = []

    for page in pages:
        for warning in page.get("warnings", []):
            warnings.append(
                f"Page {page.get('page')}: {warning}"
            )

    total_characters = sum(
        len(page.get("text", ""))
        for page in pages
    )

    return {
        "total_pages": total_pages,
        "pages_with_text": pages_with_text,
        "ocr_pages": ocr_pages,
        "total_characters": total_characters,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Command-line test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "    python extractor.py <pdf_path>"
        )
        raise SystemExit(1)

    pdf_path = sys.argv[1]

    pages = extract_pdf_text(pdf_path)

    print(
        json.dumps(
            pages,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n--- EXTRACTION SUMMARY ---")

    print(
        json.dumps(
            extraction_summary(pages),
            indent=2,
            ensure_ascii=False,
        )
    )