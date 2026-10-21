from __future__ import annotations

import datetime as dt

import pytest

from core.validation import InvalidPDFError, UnsafeURLError, canonicalize_url, check_url_allowed, validate_pdf_file
from services.metadata import (
    classify_document_type,
    clean_text,
    detect_language,
    normalize_department,
    parse_date,
    script_profile,
    to_ascii_digits,
)
from tests.conftest import make_pdf

MARATHI = "शासन निर्णय: ग्रामीण भागातील रस्त्यांच्या दुरुस्तीबाबत आणि निधी वितरणाबाबत आहे."
HINDI = "मध्यप्रदेश शासन द्वारा दिव्यांगजन के रिक्त पदों की पूर्ति के संबंध में आदेश जारी किया गया है।"
ODIA = "ଓଡ଼ିଶା ସରକାର ଅନୁସୂଚିତ ଜନଜାତି ଓ ଅନୁସୂଚିତ ଜାତି ଉନ୍ନୟନ ବିଭାଗ ସଂକଳ୍ପ"


@pytest.mark.parametrize("text,expected", [
    ("21-10-2026", dt.date(2026, 10, 21)),
    ("29/08/2026", dt.date(2026, 8, 29)),
    ("२१-१०-२०२६", dt.date(2026, 10, 21)),
    ("୦୮-୧୦-୨୦୨୬", dt.date(2026, 10, 8)),
    ("2026-06-12", dt.date(2026, 6, 12)),
    ("16-Mar-2018", dt.date(2018, 3, 16)),
    ("31-02-2026", None),
    ("not a date", None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_indic_digits():
    assert to_ascii_digits("पान २५ / ୧୨") == "पान 25 / 12"


@pytest.mark.parametrize("text,lang", [(MARATHI, "mr"), (HINDI, "hi"), (ODIA, "or"), ("Government Resolution regarding pay", "en")])
def test_language_detection(text, lang):
    assert detect_language(text) == lang


def test_unicode_preserved_by_clean_text():
    for s in (MARATHI, HINDI, ODIA, "सामाजिक न्‍याय"):
        assert clean_text(s) == s  # NFC, ZWJ kept, nothing transliterated
    assert clean_text("a​b\xa0 c") == "ab c"


def test_script_profile():
    assert script_profile(ODIA)["odia"] > 0.95
    assert script_profile(MARATHI)["devanagari"] > 0.95


def test_department_suffix_stripped():
    assert normalize_department("ऊर्जा विभाग (पासुन २४-जून-२०२६)") == "ऊर्जा विभाग"


@pytest.mark.parametrize("title,expected", [
    ("Notification regarding fees", "notification"),
    ("Circular on leave", "circular"),
    ("Resolution on scheme", "resolution"),
    ("मंत्रिमंडळ निर्णय", "cabinet_decision"),
    ("Something else", "other"),
])
def test_classify(title, expected):
    assert classify_document_type(title) == expected


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x.pdf", "http://10.0.0.5/a", "http://localhost/a", "file:///etc/passwd",
    "https://evil.example.com/a.pdf", "https://user:pw@gr.maharashtra.gov.in/a", "http://[::1]/a",
])
def test_ssrf_rejected(url):
    with pytest.raises(UnsafeURLError):
        check_url_allowed(url, ["gr.maharashtra.gov.in"])


def test_allowlisted_url_ok():
    assert check_url_allowed("https://gr.maharashtra.gov.in/a.pdf", ["gr.maharashtra.gov.in"])


def test_canonicalize_url():
    a = canonicalize_url("https://GR.maharashtra.gov.in:443/Site/Upload/Government Resolutions/x.pdf#frag")
    b = canonicalize_url("https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/x.pdf")
    assert a == b


def test_valid_pdf(tmp_path):
    assert validate_pdf_file(make_pdf(tmp_path / "a.pdf")) == 1


def test_invalid_pdf_rejected(tmp_path):
    html = tmp_path / "h.pdf"
    html.write_bytes(b"<html><body>Not found</body></html>" * 20)
    with pytest.raises(InvalidPDFError, match="signature"):
        validate_pdf_file(html)


def test_truncated_pdf_rejected(tmp_path):
    good = make_pdf(tmp_path / "a.pdf").read_bytes()
    bad = tmp_path / "t.pdf"
    bad.write_bytes(good[: len(good) // 2])
    with pytest.raises(InvalidPDFError):
        validate_pdf_file(bad)
