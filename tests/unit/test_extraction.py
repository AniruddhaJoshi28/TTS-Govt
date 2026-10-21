import io
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfWriter

from services.metadata_extraction.normalise import extract_amounts, extract_dates, normalise_digits
from services.pdf_ocr.extract import InvalidPdf, detect_scripts, extract_pages
from tests.helpers import make_pdf


def test_embedded_text_page():
    (page,) = extract_pages(make_pdf("Government Resolution dated 01/04/2026"))
    assert page.method == "embedded" and page.page == 1
    assert "Government Resolution" in page.text


def test_page_without_text_is_flagged_for_ocr():
    (page,) = extract_pages(make_pdf(None))
    assert page.method == "needs_ocr" and page.text == ""


def test_non_pdf_rejected():
    with pytest.raises(InvalidPdf, match="not a PDF"):
        extract_pages(b"<html>error page</html>")


def test_truncated_pdf_rejected():
    with pytest.raises(InvalidPdf):
        extract_pages(make_pdf("Government Resolution text")[:60])


def test_encrypted_pdf_rejected():
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.encrypt("secret")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(InvalidPdf, match="password"):
        extract_pages(buf.getvalue())


def test_script_detection():
    assert detect_scripts("शासन निर्णय GR") == {"devanagari": 10, "latin": 2}  # vowel signs count as code points
    assert set(detect_scripts("ଓଡ଼ିଶା ସରକାର")) == {"odia"}


def test_devanagari_and_odia_digits_normalised():
    assert normalise_digits("दिनांक १५/०८/२०२६") == "दिनांक 15/08/2026"
    assert normalise_digits("୨୦୨୬") == "2026"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("दिनांक १५/०८/२०२६ रोजी", date(2026, 8, 15)),
        ("dated 01.04.2026", date(2026, 4, 1)),
        ("ତାରିଖ ୦୨-୧୦-୨୦୨୬", date(2026, 10, 2)),
    ],
)
def test_dates_are_day_first(text, expected):
    (d,) = extract_dates(text)
    assert d.value == expected
    assert text[d.span[0]:d.span[1]] == d.raw


def test_invalid_date_is_dropped_not_guessed():
    assert extract_dates("31/02/2026") == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("अनुदान ₹ 1,50,000 देय", Decimal("150000")),
        ("रु. ५०००", Decimal("5000")),
        ("Rs. 2,500.50 only", Decimal("2500.50")),
        ("10,000 रुपये मिलेंगे", Decimal("10000")),
        ("୧୦୦୦ ଟଙ୍କା", Decimal("1000")),
        ("ରୁ. 12,34,567", Decimal("1234567")),
    ],
)
def test_amounts(text, expected):
    (a,) = extract_amounts(text)
    assert a.value == expected


def test_bare_number_is_not_an_amount():
    assert extract_amounts("GR क्रमांक 2026/12") == []


def test_pypdf_crash_on_a_page_routes_it_to_ocr(monkeypatch):
    # Seen on a real MH GR: pypdf raised TypeError (float + IndirectObject) in a font width table.
    from pypdf import PageObject

    from services.pdf_ocr.extract import extract_pages
    from tests.helpers import make_pdf

    def boom(self, *a, **k):
        raise TypeError("unsupported operand type(s) for +: 'float' and 'IndirectObject'")

    monkeypatch.setattr(PageObject, "extract_text", boom)
    pages = extract_pages(make_pdf("Some embedded text that would normally be read directly"))
    assert pages[0].method == "needs_ocr" and pages[0].reason == "corrupt_encoding"
