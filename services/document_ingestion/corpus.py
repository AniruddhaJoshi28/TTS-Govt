"""Builds the searchable corpus: PDF → pages (embedded text or OCR) → passages.

Each page records how its text was obtained and which numbers are untrusted.
Human corrections from data/review/<doc_id>.yaml are applied only when they
name a reviewer; a corrected span becomes trusted, everything else keeps its
OCR flags. Portal listing metadata becomes its own citable passage.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import pypdfium2 as pdfium
import yaml
from pydantic import BaseModel

from services.document_ingestion.manifest import DocumentEntry
from services.metadata_extraction.critical import untrusted_spans
from services.pdf_ocr.extract import extract_pages
from services.pdf_ocr.ocr import OCR_LANGS, OcrPage, TesseractOcr
from services.retrieval.bm25 import Passage

MAX_PASSAGE_CHARS = 700
REVIEW_DIR = Path(__file__).parents[2] / "data" / "review"
METADATA_PAGE = 0  # passages from the portal listing, not from a PDF page


class Correction(BaseModel):
    page: int
    find: str
    replace: str
    reviewer: str | None = None
    reviewed_at: str | None = None
    note: str = ""


class Transcription(BaseModel):
    """A reviewer's transcription of part of a page, typically a critical table."""

    page: int
    text: str
    proposed_by: str = ""
    reviewer: str | None = None
    reviewed_at: str | None = None

    @property
    def signed(self) -> bool:
        return bool(self.reviewer and self.reviewed_at)


class PageRecord(BaseModel):
    page: int
    origin: str  # "embedded" | "ocr"
    reason: str | None = None
    text: str
    ocr_mean_conf: float | None = None
    untrusted: list[tuple[int, int]] = []
    corrected: list[tuple[int, int]] = []


class CorpusDocument(BaseModel):
    entry: DocumentEntry
    sha256: str
    retrieved_at: datetime
    pages: list[PageRecord]
    passages: list[dict]

    def to_passages(self) -> list[Passage]:
        return [Passage(**{**p, "untrusted": tuple(tuple(s) for s in p["untrusted"])}) for p in self.passages]


def load_review(doc_id: str, review_dir: Path = REVIEW_DIR) -> tuple[list[Correction], list[Transcription]]:
    path = review_dir / f"{doc_id}.yaml"
    if not path.exists():
        return [], []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ([Correction.model_validate(c) for c in raw.get("corrections") or []],
            [Transcription.model_validate(t) for t in raw.get("transcriptions") or []])


def apply_corrections(text: str, corrections: list[Correction]) -> tuple[str, list[tuple[int, int]]]:
    """Apply reviewer-signed corrections; return new text and the corrected spans."""
    spans: list[tuple[int, int]] = []
    for c in corrections:
        if not (c.reviewer and c.reviewed_at):
            continue
        idx = text.find(c.find)
        if idx < 0:
            continue
        text = text[:idx] + c.replace + text[idx + len(c.find):]
        delta = len(c.replace) - len(c.find)
        spans = [(s + delta, e + delta) if s > idx else (s, e) for s, e in spans]
        spans.append((idx, idx + len(c.replace)))
    return text, spans


def _overlaps(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    return any(span[0] < e and s < span[1] for s, e in others)


def chunk(text: str, max_chars: int = MAX_PASSAGE_CHARS) -> list[tuple[int, int]]:
    """Split on blank lines, merge short paragraphs, split long ones at sentence ends."""
    paras = [(m.start(), m.end()) for m in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, flags=re.S)]
    pieces: list[tuple[int, int]] = []
    for s, e in paras:
        while e - s > max_chars:
            window = text[s:s + max_chars]
            cut = max(window.rfind("।"), window.rfind(". "), window.rfind("\n"))
            cut = s + (cut + 1 if cut > max_chars // 3 else max_chars)
            pieces.append((s, cut))
            s = cut
            while s < e and text[s].isspace():
                s += 1
        if s < e:
            pieces.append((s, e))
    merged: list[tuple[int, int]] = []
    for s, e in pieces:
        if merged and (e - merged[-1][0]) <= max_chars and (merged[-1][1] - merged[-1][0]) < max_chars // 3:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def build_document(
    entry: DocumentEntry,
    pdf: bytes,
    sha256: str,
    retrieved_at: datetime,
    ocr: TesseractOcr | None,
    corrections: list[Correction] = (),
    transcriptions: list[Transcription] = (),
    force_ocr_pages: frozenset[int] = frozenset(),
) -> CorpusDocument:
    """``force_ocr_pages``: 1-based pages whose embedded text is known to be corrupt (e.g. flagged by
    the crawler's glyph-order / broken-ToUnicode checks); they are OCR'd, or left empty without OCR."""
    pages: list[PageRecord] = []
    for p in extract_pages(pdf):
        ocr_page: OcrPage | None = None
        if p.page in force_ocr_pages and ocr is None:
            text, origin, conf = "", "ocr", None
        elif p.page in force_ocr_pages:
            ocr_page = ocr.page(pdf, p.page, OCR_LANGS[entry.language.value])
            text, origin, conf = ocr_page.text, "ocr", round(ocr_page.mean_conf, 1)
        elif p.method == "embedded":
            text, origin, conf = p.text, "embedded", None
        elif ocr is None:
            text, origin, conf = "", "ocr", None
        else:
            ocr_page = ocr.page(pdf, p.page, OCR_LANGS[entry.language.value])
            text, origin, conf = ocr_page.text, "ocr", round(ocr_page.mean_conf, 1)
        flagged = untrusted_spans(text, ocr_page)
        page_fixes = [c for c in corrections if c.page == p.page]
        if page_fixes:
            # Offsets shift after corrections; re-flag the corrected text without
            # word confidences, then trust only what a reviewer signed.
            text, corrected = apply_corrections(text, page_fixes)
            flagged = [s for s in untrusted_spans(text) if not _overlaps(s, corrected)]
        else:
            corrected = []
        pages.append(PageRecord(page=p.page, origin=origin, reason=p.reason, text=text,
                                ocr_mean_conf=conf, untrusted=flagged, corrected=corrected))

    passages = []
    if entry.portal_metadata:
        meta = "\n".join(f"{k}: {v}" for k, v in entry.portal_metadata.items())
        passages.append(dict(passage_id=f"{entry.id}:meta", document_id=entry.id, version_id=sha256[:12],
                             url=str(entry.listing_url), page=METADATA_PAGE, text=meta,
                             origin="portal_metadata", untrusted=[]))
    for page in pages:
        for n, (s, e) in enumerate(chunk(page.text), start=1):
            local = [(a - s, b - s) for a, b in page.untrusted if a < e and s < b]
            local = [(max(a, 0), min(b, e - s)) for a, b in local]
            passages.append(dict(passage_id=f"{entry.id}:p{page.page}:{n}", document_id=entry.id,
                                 version_id=sha256[:12], url=str(entry.url), page=page.page,
                                 text=page.text[s:e], origin=page.origin if not page.corrected else "reviewed",
                                 untrusted=local))
    for n, t in enumerate((t for t in transcriptions if t.signed), start=1):
        passages.append(dict(passage_id=f"{entry.id}:p{t.page}:reviewed{n}", document_id=entry.id,
                             version_id=sha256[:12], url=str(entry.url), page=t.page, text=t.text,
                             origin="reviewed", untrusted=[]))
    return CorpusDocument(entry=entry, sha256=sha256, retrieved_at=retrieved_at, pages=pages, passages=passages)


def render_page_images(pdf: bytes, out_dir: Path, dpi: int = 110) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(pdf)
    paths = []
    try:
        for i in range(len(doc)):
            path = out_dir / f"page-{i + 1}.png"
            doc[i].render(scale=dpi / 72).to_pil().save(path)
            paths.append(path)
    finally:
        doc.close()
    return paths


def save(doc: CorpusDocument, corpus_dir: Path) -> Path:
    out = corpus_dir / doc.entry.id
    out.mkdir(parents=True, exist_ok=True)
    path = out / "document.json"
    path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_corpus(corpus_dir: Path) -> dict[str, CorpusDocument]:
    docs = {}
    for path in sorted(corpus_dir.glob("*/document.json")):
        doc = CorpusDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        docs[doc.entry.id] = doc
    return docs
