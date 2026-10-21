"""Deterministic metadata normalisation. No ML: rules, Unicode script ranges and explicit vocabularies.

Original Unicode text is never altered beyond whitespace collapsing; Indic digits are only
converted in fields that are semantically numeric (dates, page numbers).
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

_INDIC_DIGIT_BASES = {
    0x0966: "devanagari",  # Marathi / Hindi
    0x0B66: "odia",
    0x09E6: "bengali",
    0x0AE6: "gujarati",
}
_DIGIT_MAP = {base + i: str(i) for base in _INDIC_DIGIT_BASES for i in range(10)}

SCRIPT_RANGES = {
    "devanagari": (0x0900, 0x097F),
    "odia": (0x0B00, 0x0B7F),
    "latin": (0x0041, 0x024F),
}


def to_ascii_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


def clean_text(text: str | None) -> str:
    """Collapse whitespace and drop zero-width-space artefacts, preserving ZWJ/ZWNJ (meaningful in Indic scripts)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text).replace("​", "").replace("\xa0", " ")
    return " ".join(text.split())


_MONTHS = {m.lower(): i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_date(text: str | None) -> dt.date | None:
    """Parse the date formats seen on the audited portals: DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY,
    YYYY-MM-DD, DD-Mon-YYYY; Indic digits accepted."""
    if not text:
        return None
    t = to_ascii_digits(clean_text(text))
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe_date(y, mo, d)
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", t)
    if m:
        d, mo, y = map(int, m.groups())
        return _safe_date(y, mo, d)
    m = re.search(r"\b(\d{1,2})[-\s]([A-Za-z]{3})[A-Za-z]*[-\s,]+(\d{4})\b", t)
    if m and m.group(2).lower() in _MONTHS:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        date = dt.date(y, m, d)
    except ValueError:
        return None
    if not (1900 <= date.year <= dt.date.today().year + 1):
        return None
    return date


def script_profile(text: str) -> dict[str, float]:
    """Share of letters per script (devanagari / odia / latin / other)."""
    counts = {k: 0 for k in SCRIPT_RANGES} | {"other": 0}
    total = 0
    for ch in text:
        if not ch.isalpha() and unicodedata.category(ch) not in ("Mn", "Mc"):
            continue
        total += 1
        cp = ord(ch)
        for name, (lo, hi) in SCRIPT_RANGES.items():
            if lo <= cp <= hi:
                counts[name] += 1
                break
        else:
            counts["other"] += 1
    if not total:
        return {}
    return {k: round(v / total, 4) for k, v in counts.items() if v}


# Very small, explicit Marathi-vs-Hindi discriminator vocabularies (high-frequency function words).
_MARATHI_MARKERS = ("आहे", "बाबत", "शासन निर्णय", "करण्यात", "यांच्या", "विभागाचे", "सन ", "आणि", "च्या")
_HINDI_MARKERS = ("है", "के संबंध", "किया", "हेतु", "एवं", "द्वारा", "की ", "में ", "और")


def detect_language(text: str, state_hint: str | None = None) -> str | None:
    """Return ISO-639-1 code (mr/hi/or/en) or None. Script first, then lexical markers, then state hint."""
    prof = script_profile(text)
    if not prof:
        return None
    if prof.get("odia", 0) >= 0.3:
        return "or"
    if prof.get("devanagari", 0) >= 0.3:
        mr = sum(text.count(w) for w in _MARATHI_MARKERS)
        hi = sum(text.count(w) for w in _HINDI_MARKERS)
        if mr > hi:
            return "mr"
        if hi > mr:
            return "hi"
        return {"maharashtra": "mr", "madhya_pradesh": "hi"}.get(state_hint or "", "hi")
    if prof.get("latin", 0) >= 0.5:
        return "en"
    return None


_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("gazette", ("gazette", "राजपत्र", "ରାଜପତ୍ର")),
    ("cabinet_decision", ("cabinet decision", "मंत्रिमंडळ निर्णय", "मंत्रिपरिषद")),
    ("notification", ("notification", "अधिसूचना", "ଅଧିସୂଚନା")),
    ("office_order", ("office order",)),
    ("circular", ("circular", "परिपत्रक", "परिपत्र", "ପରିପତ୍ର")),
    ("memorandum", ("memorandum", "office memo", "ज्ञापन")),
    ("resolution", ("resolution", "संकल्प", "ସଂକଳ୍ପ")),
    ("order", (" order", "आदेश", "ଆଦେଶ")),
]


def classify_document_type(title: str, default: str = "other") -> str:
    """Keyword classification from the title; falls back to the listing's declared type."""
    t = f" {title.lower()} "
    for doc_type, keys in _TYPE_RULES:
        if any(k in t for k in keys):
            return doc_type
    return default


def normalize_department(name: str | None) -> str | None:
    """Strip validity suffixes such as '(पासुन २४-जून-२०२६)' that MH appends to renamed departments."""
    if not name:
        return None
    name = clean_text(name)
    name = re.sub(r"\s*\((?:पासुन|पासून|from)\s[^)]*\)\s*$", "", name, flags=re.IGNORECASE)
    return name or None
