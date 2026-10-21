"""Page-level text extraction with quality diagnostics.

PyMuPDF is the primary extractor; pypdf is a fallback for pages PyMuPDF cannot read.
Each page is scored so OCR can be targeted at pages whose text layer is missing or unusable
(e.g. scanned pages, or legacy non-Unicode Devanagari fonts that extract as Latin gibberish).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.metadata import clean_text, script_profile

logger = logging.getLogger(__name__)

EXPECTED_SCRIPT = {"mr": "devanagari", "hi": "devanagari", "or": "odia", "en": "latin"}


@dataclass
class PageText:
    page_number: int
    text: str
    method: str
    char_count: int
    script_profile: dict[str, float]
    usable: bool
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None


_INDIC_SIGN_CATEGORIES = ("Mn", "Mc")
# Two dependent vowel signs in a row (e.g. "ा" + "ि") never occur in well-formed Devanagari/Odia.
_DOUBLE_MATRA = re.compile("[ा-ौା-ୌ][ा-ौା-ୌ]")


def _is_indic_sign(ch: str) -> bool:
    cp = ord(ch)
    return (0x0900 <= cp <= 0x097F or 0x0B00 <= cp <= 0x0B7F) and unicodedata.category(ch) in _INDIC_SIGN_CATEGORIES


def text_defects(text: str) -> dict[str, float]:
    """Deterministic signals of a broken text layer.

    * ``pua``: Private-Use-Area code points — glyph IDs leaking out of fonts without a ToUnicode map.
    * ``control``: C0 control characters other than whitespace — same cause.
    * ``orphan_signs``: Indic dependent vowel signs / virama that start a word or follow a space,
      which is impossible in well-formed Unicode and typical of mis-ordered glyph extraction.
    """
    n = max(1, len(text))
    pua = sum(1 for c in text if 0xE000 <= ord(c) <= 0xF8FF)
    control = sum(1 for c in text if ord(c) < 32 and c not in "\n\r\t\f")
    words = text.split()
    orphan = sum(1 for w in words if w and (_is_indic_sign(w[0]) or _DOUBLE_MATRA.search(w)))
    indic_words = sum(1 for w in words if any(0x0900 <= ord(c) <= 0x0B7F for c in w)) or 1
    return {"pua": round(pua / n, 4), "control": round(control / n, 4), "orphan_signs": round(orphan / indic_words, 4)}


def assess_text(text: str, expected_language: str | None, min_chars: int) -> tuple[bool, str, dict[str, float]]:
    stripped = clean_text(text)
    prof = script_profile(stripped)
    letters = sum(1 for c in stripped if c.isalpha())
    if letters < min_chars:
        return False, "no_text_layer" if letters == 0 else "too_little_text", prof
    expected = EXPECTED_SCRIPT.get(expected_language or "")
    if expected and expected != "latin":
        share = prof.get(expected, 0.0)
        if share < 0.15 and prof.get("latin", 0) + prof.get("other", 0) > 0.7:
            # Indic documents typeset with legacy 8-bit fonts extract as Latin/symbol gibberish.
            return False, "legacy_font_suspected", prof
    replacement = stripped.count("�")
    if replacement > 0.05 * max(1, len(stripped)):
        return False, "replacement_chars", prof
    defects = text_defects(stripped)
    if defects["pua"] > 0.005 or defects["control"] > 0.005:
        return False, "broken_unicode_mapping", prof
    if defects["orphan_signs"] > 0.05:
        return False, "glyph_order_errors", prof
    return True, "ok", prof


def text_confidence(text: str) -> float:
    """Heuristic 0..1 quality score for an extracted text layer (1 = no detectable defects)."""
    d = text_defects(clean_text(text))
    return round(max(0.0, 1.0 - 20 * d["pua"] - 20 * d["control"] - 5 * d["orphan_signs"]), 3)


def extract_pages(path: Path, expected_language: str | None = None, min_chars: int = 40) -> list[PageText]:
    import pymupdf as fitz

    pages: list[PageText] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            method = "pymupdf"
            diag: dict[str, Any] = {"images": len(page.get_images(full=False))}
            try:
                text = page.get_text("text")
            except Exception as exc:  # pragma: no cover - corrupt page objects
                diag["pymupdf_error"] = str(exc)
                text = _pypdf_page_text(path, i - 1)
                method = "pypdf"
            usable, reason, prof = assess_text(text, expected_language, min_chars)
            if not usable and reason != "legacy_font_suspected" and method == "pymupdf":
                alt = _pypdf_page_text(path, i - 1)
                alt_ok, alt_reason, alt_prof = assess_text(alt, expected_language, min_chars)
                if alt_ok:
                    text, method, usable, reason, prof = alt, "pypdf", alt_ok, alt_reason, alt_prof
            if diag["images"] and not usable:
                diag["likely_scanned"] = True
            diag["defects"] = text_defects(clean_text(text))
            pages.append(PageText(i, text, method, len(clean_text(text)), prof, usable, reason, diag,
                                  confidence=text_confidence(text) if text.strip() else 0.0))
    return pages


def _pypdf_page_text(path: Path, index: int) -> str:
    try:
        from pypdf import PdfReader

        return PdfReader(str(path)).pages[index].extract_text() or ""
    except Exception as exc:
        logger.debug("pypdf failed on page %s: %s", index, exc)
        return ""


def guess_document_language(pages: list[PageText], state: str | None) -> str | None:
    from services.metadata import detect_language

    sample = " ".join(p.text for p in pages if p.usable)[:20000]
    return detect_language(sample, state) if sample else None
