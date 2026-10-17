"""Excerpts below are short quotations from real public GRs, used as regression data."""

from services.factual_validation.validate import Claim, ModelAnswer, numbers, validate
from services.metadata_extraction.critical import mask, untrusted_spans
from services.pdf_ocr.ocr import OcrPage, OcrWord, parse_tsv
from services.pdf_ocr.quality import assess
from tests.helpers import passage

# Maharashtra Public Health circular, embedded text layer (legacy font encoding).
GARBLED = (
    "आरोग्य सेवाांमध्ये पारदर्शकता आणण्यासाठी राज्यातील सवश खाजगी क्ललननकल एस्टॅक्ललर्मेंट्स "
    "महाराष्ट्र र्ासन सावशजननक आरोग्य नवभाग र्ासन पनरपत्रक क्रमाांक: सांकीणश -२०२६/प्र.क्र. २४७ "
    "भारत सरकारच्या आरोग्य आनण क ु टुांब कल्याण मांत्रालयाचे पत्र क्र. सवश आरोग्य सेवा सांस्थामध्ये"
)
# The same passage after OCR.
CLEAN = (
    "आरोग्य सेवांमध्ये पारदर्शकता आणण्यासाठी राज्यातील सर्व खाजगी क्लिनिकल एस्टॅब्लिशमेंट्स "
    "महाराष्ट्र शासन सार्वजनिक आरोग्य विभाग शासन परिपत्रक क्रमांक: संकीर्ण -२०२६/प्र.क्र. २४७ "
    "भारत सरकारच्या आरोग्य आणि कुटुंब कल्याण मंत्रालयाचे पत्र क्र. सर्व आरोग्य सेवा संस्थामध्ये"
)
ODIA_CLEAN = "ଯେହେତୁ ଓଡ଼ିଶା ସରକାରଙ୍କ ଶ୍ରମ ଓ କର୍ମଚାରୀ ରାଜ୍ୟ ବୀମା ବିଭାଗଙ୍କ ଦ୍ବାରା ଜାରି ହୋଇଥିବା ବିଜ୍ଞପ୍ତି ଅନୁଯାୟୀ ରାଜ୍ୟରେ କାର୍ଯ୍ୟରତ"


def test_legacy_encoding_is_detected():
    q = assess(GARBLED)
    assert not q.ok and q.anomalies >= 3


def test_clean_text_passes():
    assert assess(CLEAN).ok
    assert assess(ODIA_CLEAN).ok


def test_short_text_is_not_judged():
    assert assess("क ु").ok


def test_confusable_digits_are_untrusted():
    # MP minimum-wage order: "01.10.2026" OCR'd as "0।.0.2026".
    text = "दिनांक 0।.0.2026 से 3.03.2027 तक, अकुशल रूपये 450/-"
    spans = untrusted_spans(text)
    flagged = [text[s:e] for s, e in spans]
    assert "0।.0.2026" in flagged
    assert not any("450" in f for f in flagged)


def test_impossible_date_is_untrusted():
    text = "दिनांक 34.03.2027 तक"
    assert [text[s:e] for s, e in untrusted_spans(text)] == ["34.03.2027"]


def test_low_confidence_numeric_word_is_untrusted():
    ocr = OcrPage(1, "अकुशल 484 रुपये", [OcrWord("अकुशल", 95, 0, 5), OcrWord("484", 41, 6, 9), OcrWord("रुपये", 96, 10, 15)])
    assert untrusted_spans(ocr.text, ocr) == [(6, 9)]


def test_mask_preserves_offsets():
    assert mask("abc 123 def", [(4, 7)]) == "abc     def"


def test_claim_using_untrusted_number_is_rejected():
    text = "अकुशल श्रमिक की दैनिक दर 484 रुपये"
    p = passage("p1", text)
    p_flagged = passage("p1", text, untrusted=((text.index("484"), text.index("484") + 3),))
    claim = ModelAnswer(claims=[Claim(text="अकुशल श्रमिक को 484 रुपये प्रतिदिन", citations=["p1"])])
    assert validate(claim, [p]).accepted
    assert not validate(claim, [p_flagged]).accepted


def test_any_number_must_appear_in_evidence():
    p = passage("p1", "67 अनुसूचित नियोजनों में दरें लागू")
    bad = ModelAnswer(claims=[Claim(text="76 नियोजनों में लागू", citations=["p1"])])
    assert not validate(bad, [p]).accepted


def test_number_normalisation():
    assert numbers("୦୧.୧୦.୨୦୨୬ ରୁ ୪୭୮ ଟଙ୍କା, ₹ 1,50,000") == {"1", "10", "2026", "478", "150000"}


def test_parse_tsv_rebuilds_lines_and_offsets():
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t96.0\tमहाराष्ट्र",
        "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t91.5\tशासन",
        "5\t1\t1\t1\t2\t1\t0\t0\t1\t1\t60.0\t१६",
        "5\t1\t1\t2\t1\t1\t0\t0\t1\t1\t88.0\tवाचा",
    ]
    page = parse_tsv(1, "\n".join([header, *rows]))
    assert page.text == "महाराष्ट्र शासन\n१६\n\nवाचा"
    w = page.words[2]
    assert page.text[w.start:w.end] == "१६" and w.conf == 60.0


def test_plain_text_instead_of_tsv_is_an_error():
    # Seen on the GPU server: without tessdata/configs, "tsv" silently produced plain text.
    import pytest

    from services.pdf_ocr.ocr import OcrUnavailable

    with pytest.raises(OcrUnavailable, match="did not return TSV"):
        parse_tsv(1, "आरोग्य सेवांमध्ये पारदर्शकता\nराज्यातील सर्व खाजगी")
