"""PDF validation and page-level text extraction (Workstream B, steps 1–2, 5, 8).

Pages without usable embedded text are marked ``needs_ocr`` rather than
returned as empty text, so scanned GRs are never silently treated as blank.
OCR itself (script-appropriate engines for Marathi, Hindi and Odia) plugs in
behind that flag.
"""

import io
import logging
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logging.getLogger("pypdf").setLevel(logging.ERROR)

MIN_TEXT_CHARS = 20

SCRIPT_RANGES = {
    "devanagari": (0x0900, 0x097F),  # Marathi and Hindi share this script
    "odia": (0x0B00, 0x0B7F),
}


class InvalidPdf(ValueError):
    pass


@dataclass(frozen=True)
class PageText:
    page: int  # 1-based, for citations
    method: Literal["embedded", "needs_ocr"]
    text: str
    scripts: dict[str, int]


def detect_scripts(text: str) -> dict[str, int]:
    """Code-point counts per script (vowel signs included). Telling Marathi from Hindi needs a language model, not script ranges."""
    counts = {"devanagari": 0, "odia": 0, "latin": 0}
    for ch in text:
        cp = ord(ch)
        for name, (lo, hi) in SCRIPT_RANGES.items():
            if lo <= cp <= hi:
                counts[name] += 1
                break
        else:
            if ch.isascii() and ch.isalpha():
                counts["latin"] += 1
    return {k: v for k, v in counts.items() if v}


def extract_pages(content: bytes) -> list[PageText]:
    if not content.lstrip()[:5] == b"%PDF-":
        raise InvalidPdf("not a PDF file")
    try:
        reader = PdfReader(io.BytesIO(content))
    except (PdfReadError, ValueError, OSError) as exc:
        raise InvalidPdf(f"corrupt or truncated PDF: {exc}") from exc
    if reader.is_encrypted:
        raise InvalidPdf("password-protected PDF")

    pages = []
    try:
        for i, page in enumerate(reader.pages, start=1):
            text = unicodedata.normalize("NFC", page.extract_text() or "").strip()
            usable = sum(1 for ch in text if not ch.isspace()) >= MIN_TEXT_CHARS
            pages.append(
                PageText(page=i, method="embedded" if usable else "needs_ocr", text=text if usable else "",
                         scripts=detect_scripts(text) if usable else {})
            )
    except (PdfReadError, ValueError, KeyError) as exc:
        raise InvalidPdf(f"corrupt PDF page structure: {exc}") from exc
    if not pages:
        raise InvalidPdf("PDF has no pages")
    return pages
