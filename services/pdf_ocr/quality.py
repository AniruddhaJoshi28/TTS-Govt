"""Detects embedded PDF text that is corrupted by legacy Indic font encodings.

Many Maharashtra GRs are typeset with non-Unicode Devanagari fonts. Their text
layer extracts without errors but is wrong ("शासन निर्णय" comes out as
"शासन रनिवय", "सेवांमध्ये" as "सेवाांमध्ये"). Such pages must be OCR'd instead.

Two structural anomalies never occur in well-formed Unicode text:
- the same vowel sign twice in a row (e.g. "ाा");
- a vowel sign, virama or nukta directly after a space ("क ु टुांब").
"""

import unicodedata
from dataclasses import dataclass

INDIC_BLOCKS = ((0x0900, 0x097F), (0x0B00, 0x0B7F))
# Anomalies per 1000 Indic characters above which a page is treated as corrupted.
MAX_ANOMALY_RATE = 2.0
MIN_INDIC_CHARS = 50


def _is_indic(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in INDIC_BLOCKS)


def _is_mark(ch: str) -> bool:
    return _is_indic(ch) and unicodedata.category(ch) in ("Mn", "Mc")


@dataclass(frozen=True)
class TextQuality:
    ok: bool
    indic_chars: int
    anomalies: int

    @property
    def anomaly_rate(self) -> float:
        return 1000 * self.anomalies / self.indic_chars if self.indic_chars else 0.0


def assess(text: str) -> TextQuality:
    indic = sum(1 for ch in text if _is_indic(ch))
    anomalies = 0
    for prev, ch in zip(text, text[1:]):
        if _is_mark(ch) and (prev == ch or prev in " \t"):
            anomalies += 1
    if indic < MIN_INDIC_CHARS:
        return TextQuality(True, indic, anomalies)
    rate = 1000 * anomalies / indic
    return TextQuality(rate <= MAX_ANOMALY_RATE, indic, anomalies)
