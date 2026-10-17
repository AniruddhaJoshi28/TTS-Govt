"""Flags numbers that OCR may have misread (plan §4: OCR corruption in critical field).

On real scanned orders Tesseract confuses the digit 1 with "।", "I", "!" or
"|", so "01.10.2026" becomes "0।.0.2026". A number is untrusted when:
- it touches one of those confusable characters,
- it is part of an impossible date (e.g. 34.03.2027), or
- the OCR engine was not confident about the word containing it.

Untrusted spans are excluded from the evidence used to validate claims, so a
summary can never state a value that only an unreliable reading supports.
"""

import re
from datetime import date

from services.metadata_extraction.normalise import normalise_digits
from services.pdf_ocr.ocr import OcrPage

MIN_NUMBER_CONF = 80.0

_DIGIT = r"[0-9०-९୦-୯]"
_CONFUSABLE = r"[।॥Il|!]"
_TOKEN = re.compile(rf"(?:{_CONFUSABLE}*{_DIGIT}[{_DIGIT[1:-1]}।॥Il|!.,/\-:]*)")
_DATE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")


def _has_digit(s: str) -> bool:
    return bool(re.search(_DIGIT, s))


def untrusted_spans(text: str, ocr: OcrPage | None = None, min_conf: float = MIN_NUMBER_CONF) -> list[tuple[int, int]]:
    spans = []
    for m in _TOKEN.finditer(text):
        if re.search(rf"{_DIGIT}{_CONFUSABLE}|{_CONFUSABLE}{_DIGIT}", m.group()):
            spans.append(m.span())
    norm = normalise_digits(text)
    for m in _DATE.finditer(norm):
        d, mo, y = (int(g) for g in m.groups())
        try:
            date(y, mo, d)
        except ValueError:
            spans.append(m.span())
    if ocr is not None:
        spans += [(w.start, w.end) for w in ocr.words if w.conf < min_conf and _has_digit(w.text)]
    return sorted(set(spans))


def mask(text: str, spans: list[tuple[int, int]]) -> str:
    """Blank out untrusted spans, preserving length so other offsets stay valid."""
    chars = list(text)
    for start, end in spans:
        for i in range(start, min(end, len(chars))):
            chars[i] = " "
    return "".join(chars)
