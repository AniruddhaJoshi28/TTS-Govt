from datetime import date, datetime, timezone

from services.document_ingestion.corpus import Correction, Transcription, apply_corrections, build_document, chunk
from services.document_ingestion.manifest import DocumentEntry, load_manifest
from services.factual_validation.validate import trusted_text
from services.pdf_ocr.ocr import OcrPage, OcrWord
from tests.helpers import make_pdf

T0 = datetime(2026, 10, 17, tzinfo=timezone.utc)


def entry(**kw) -> DocumentEntry:
    base = dict(id="doc", state="MP", language="hi", document_type="notification", issued=date(2026, 9, 30),
                department="d", department_en="d", title="t", title_en="t",
                url="https://labour.example.gov.in/a.pdf", listing_url="https://labour.example.gov.in/list",
                fetch={"method": "direct"}, portal_metadata={"दिनांक": "30/09/2026"})
    return DocumentEntry.model_validate(base | kw)


class FakeOcr:
    def __init__(self, text: str, low_conf_word: str | None = None):
        self.text, self.low = text, low_conf_word

    def page(self, pdf, page, langs):
        words, pos = [], 0
        for w in self.text.split(" "):
            words.append(OcrWord(w, 40.0 if w == self.low else 95.0, pos, pos + len(w)))
            pos += len(w) + 1
        return OcrPage(page, self.text, words)


def test_demo_manifest_is_valid():
    entries = load_manifest()
    assert {e.state.value for e in entries} == {"MH", "MP", "OD"}


def test_chunk_respects_paragraphs_and_limit():
    text = "पहला अनुच्छेद।\n\n" + "दूसरा वाक्य। " * 120
    spans = chunk(text, max_chars=200)
    assert all(e - s <= 200 for s, e in spans)
    assert text[spans[0][0]:spans[0][1]].startswith("पहला")


def test_scanned_page_is_ocred_and_low_conf_numbers_untrusted():
    ocr = FakeOcr("अकुशल श्रमिक दैनिक दर 484 रुपये", low_conf_word="484")
    doc = build_document(entry(), make_pdf(None), "ab" * 32, T0, ocr)
    assert doc.pages[0].origin == "ocr" and doc.pages[0].reason == "no_text"
    page_passage = next(p for p in doc.to_passages() if p.page == 1)
    assert "484" not in trusted_text(page_passage)


def test_metadata_passage_is_citable():
    doc = build_document(entry(), make_pdf(None), "ab" * 32, T0, FakeOcr("x"))
    meta = doc.to_passages()[0]
    assert meta.passage_id == "doc:meta" and meta.page == 0 and "30/09/2026" in meta.text


def test_unsigned_review_items_are_ignored():
    text, spans = apply_corrections("दर 48A रुपये", [Correction(page=1, find="48A", replace="484")])
    assert text == "दर 48A रुपये" and spans == []
    unsigned = Transcription(page=1, text="अकुशल 484 रुपये प्रतिदिन", proposed_by="Claude (AI)")
    doc = build_document(entry(), make_pdf(None), "ab" * 32, T0, FakeOcr("x"), transcriptions=[unsigned])
    assert not any(p.origin == "reviewed" for p in doc.to_passages())


def test_signed_transcription_becomes_trusted_passage():
    signed = Transcription(page=1, text="अकुशल 484 रुपये प्रतिदिन", reviewer="A. Reviewer", reviewed_at="2026-10-17")
    doc = build_document(entry(), make_pdf(None), "ab" * 32, T0, FakeOcr("x"), transcriptions=[signed])
    reviewed = [p for p in doc.to_passages() if p.origin == "reviewed"]
    assert len(reviewed) == 1 and "484" in trusted_text(reviewed[0])


def test_signed_correction_replaces_and_trusts_span():
    fix = Correction(page=1, find="0।.0.2026", replace="01.10.2026", reviewer="A. Reviewer", reviewed_at="2026-10-17")
    doc = build_document(entry(), make_pdf(None), "ab" * 32, T0, FakeOcr("दिनांक 0।.0.2026 से"), corrections=[fix])
    page = doc.pages[0]
    assert "01.10.2026" in page.text and page.untrusted == []
