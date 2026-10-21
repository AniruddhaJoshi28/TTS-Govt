from __future__ import annotations

import pytest

from services.pdf_extraction import assess_text, extract_pages, text_confidence, text_defects
from tests.conftest import indic_font, make_pdf

MARATHI = "शासन निर्णय ग्रामीण भागातील रस्त्यांच्या दुरुस्तीबाबत निधी वितरण करण्यात येत आहे " * 3
HINDI = "मध्यप्रदेश शासन द्वारा दिव्यांगजन के रिक्त पदों की पूर्ति के संबंध में आदेश जारी किया गया है " * 3
ODIA = "ଓଡ଼ିଶା ସରକାର ଅନୁସୂଚିତ ଜନଜାତି ଓ ଅନୁସୂଚିତ ଜାତି ଉନ୍ନୟନ ବିଭାଗ ସଂକଳ୍ପ ଜାରି କରାଯାଇଛି " * 3


@pytest.mark.parametrize("text,lang", [(MARATHI, "mr"), (HINDI, "hi"), (ODIA, "or")])
def test_clean_indic_text_is_usable(text, lang):
    ok, reason, _ = assess_text(text, lang, 40)
    assert ok, reason
    assert text_confidence(text) == 1.0


def test_pua_glyphs_flagged():
    # Pattern observed in MP Social Justice PDFs: PUA glyph IDs mixed into Devanagari.
    broken = "मयदेशशासन सामायशासन वभाग मंालय " * 5
    ok, reason, _ = assess_text(broken, "hi", 10)
    assert not ok and reason == "broken_unicode_mapping"


def test_double_matra_glyph_errors_flagged():
    # Pattern observed in MH GR PDFs: "यािी" (ा + ि) instead of "यादी".
    broken = "सेवा जेष्ठता यािी वसूलीिाित निफारसी िुसयर " * 10
    assert text_defects(broken)["orphan_signs"] > 0.05
    ok, reason, _ = assess_text(broken, "mr", 10)
    assert not ok and reason == "glyph_order_errors"


def test_legacy_font_gibberish_flagged():
    ok, reason, _ = assess_text("ÀÉ¶ÉxÉ ÊxÉhÉÇªÉ Eò®úhªÉÉiÉ ªÉäiÉ +ÉcäÉä " * 5, "mr", 10)
    assert not ok and reason == "legacy_font_suspected"


def test_extract_digital_and_scanned_pages(tmp_path):
    pdf = make_pdf(tmp_path / "mixed.pdf", ["Digital page with plenty of searchable English text about a government resolution."],
                   blank_pages=1)
    pages = extract_pages(pdf, "en", 20)
    assert [p.usable for p in pages] == [True, False]
    assert pages[1].reason == "no_text_layer" and pages[1].diagnostics.get("likely_scanned")


@pytest.mark.skipif(indic_font() is None, reason="no Devanagari/Odia font available to build fixture")
@pytest.mark.parametrize("text,lang", [("शासन निर्णय दिनांक २१ ऑक्टोबर", "mr"), ("मध्यप्रदेश शासन आदेश", "hi"), ("ଓଡ଼ିଶା ସରକାର ସଂକଳ୍ପ", "or")])
def test_indic_unicode_roundtrip_through_pdf(tmp_path, text, lang):
    pdf = make_pdf(tmp_path / f"{lang}.pdf", [text], fontfile=indic_font())
    extracted = extract_pages(pdf, lang, 1)[0].text
    # PyMuPDF returns the ToUnicode-mapped text; compare ignoring whitespace.
    assert "".join(text.split()) in "".join(extracted.split())
