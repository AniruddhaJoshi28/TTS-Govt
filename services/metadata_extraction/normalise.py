"""Digit normalisation and extraction of dates and rupee amounts (Workstream B, step 6).

Every extracted value keeps its character span in the source text so it can
be traced back to the page. Values that do not validate (e.g. 31/02/2024) are
dropped rather than guessed.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_DIGITS = str.maketrans("०१२३४५६७८९୦୧୨୩୪୫୬୭୮୯", "01234567890123456789")


def normalise_digits(text: str) -> str:
    """Map Devanagari and Odia digits to ASCII. Length is preserved, so spans stay valid."""
    return text.translate(_DIGITS)


@dataclass(frozen=True)
class Extracted:
    value: object
    raw: str
    span: tuple[int, int]


_DATE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")

# Indian grouping (1,50,000), Western grouping (150,000) or plain digits.
_NUMBER = r"(\d{1,3}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?"
# Prefix: ₹ 1,50,000 / रु. 5000 / Rs. 2,500.50 / ରୁ 1000
# Suffix: 10,000 रुपये / 1000 ଟଙ୍କା
_AMOUNT = re.compile(
    rf"(?:₹|\bRs\.?|\bINR|रु\.?|ରୁ\.?)\s*{_NUMBER}"
    rf"|(?<![\d,]){_NUMBER}\s*(?:रुपये|रुपए|ଟଙ୍କା)"
)


def extract_dates(text: str) -> list[Extracted]:
    """Day-first dates, as used in Indian government documents."""
    norm = normalise_digits(text)
    found = []
    for m in _DATE.finditer(norm):
        d, mo, y = (int(g) for g in m.groups())
        try:
            value = date(y, mo, d)
        except ValueError:
            continue
        found.append(Extracted(value, text[m.start():m.end()], m.span()))
    return found


def extract_amounts(text: str) -> list[Extracted]:
    norm = normalise_digits(text)
    found = []
    for m in _AMOUNT.finditer(norm):
        whole = m.group(1) or m.group(3)
        frac = (m.group(2) if m.group(1) else m.group(4)) or ""
        found.append(Extracted(Decimal(whole.replace(",", "") + frac), text[m.start():m.end()], m.span()))
    return found
