"""Import documents archived by government-gr-platform (the crawler) into the assistant corpus.

Library form of scripts/import_crawled.py, used by the pipeline agents. The crawler's SQLite DB and
local object store are read directly (no platform imports: both projects have a top-level
``services`` package). Pages the crawler flagged as unusable (no text layer, broken ToUnicode maps,
Devanagari glyph-order errors) are OCR'd instead of trusting the embedded text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

from schemas.api.envelope import Language, State
from services.document_ingestion.corpus import build_document, load_corpus, render_page_images, save
from services.document_ingestion.manifest import DocumentEntry, FetchSpec
from services.pdf_ocr.ocr import OCR_LANGS, OcrUnavailable, TesseractOcr, require_languages

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = Path(os.environ.get("GR_PLATFORM_DIR", ROOT / "government-gr-platform"))
STATE_MAP = {"maharashtra": State.MAHARASHTRA, "madhya_pradesh": State.MADHYA_PRADESH, "odisha": State.ODISHA}
DEFAULT_LANG = {"maharashtra": "mr", "madhya_pradesh": "hi", "odisha": "or"}


UPLOAD_MONTH = re.compile(r"/(?:files|uploads)/(\d{4})-(\d{2})/")


def upload_month(url: str) -> date | None:
    """Month the portal published the file (Drupal stores uploads under files/YYYY-MM/)."""
    m = UPLOAD_MONTH.search(url or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def corpus_id(row: sqlite3.Row) -> str:
    state = STATE_MAP[row["state"]].value.lower()
    issued = row["publication_date"] or "undated"
    return f"{state}-{issued}-{row['pdf_sha256'][:10]}"


def unusable_pages(con: sqlite3.Connection, doc_id: str) -> frozenset[int]:
    bad = set()
    for page_no, diag in con.execute("SELECT page_number, diagnostics FROM document_pages WHERE document_id = ?", (doc_id,)):
        if not json.loads(diag or "{}").get("usable", True):
            bad.add(page_no)
    return frozenset(bad)


def entry_for(row: sqlite3.Row) -> DocumentEntry:
    lang = row["language"] if row["language"] in {l.value for l in Language} else DEFAULT_LANG[row["state"]]
    meta = {k: v for k, v in {
        "Document number": row["document_number"], "Department": row["department"],
        "Date": row["publication_date"], "Type": row["document_type"], "Source": row["source_id"],
    }.items() if v}
    if row["publication_date"]:
        issued = date.fromisoformat(row["publication_date"])
    else:
        # The portal states no date. Never use today's date (it would list old GRs as new);
        # use the upload month from the official file path and say so in the metadata.
        uploaded = upload_month(row["original_url"])
        issued = uploaded or date(1900, 1, 1)
        meta["Date"] = (f"Not stated on the portal; file uploaded {uploaded:%B %Y}" if uploaded
                        else "Not stated on the portal")
    return DocumentEntry(
        id=corpus_id(row), state=STATE_MAP[row["state"]], language=Language(lang),
        document_type=row["document_type"], issued=issued,
        # No machine translation: the English fields repeat the official text rather than invent one.
        department=row["department"] or "", department_en=row["department"] or "",
        title=row["title"], title_en=row["title"],
        url=row["original_url"], listing_url=row["listing_url"] or row["original_url"],
        fetch=FetchSpec(method="crawler", path=row["object_storage_key"]), portal_metadata=meta,
    )



def import_crawled(platform_db: Path = PLATFORM / "data" / "gr_platform.sqlite3",
                   objects: Path = PLATFORM / "data" / "objects",
                   corpus: Path = Path(os.environ.get("CORPUS_DIR", ROOT / "data" / "corpus")),
                   state: str | None = None, limit: int | None = None,
                   log: Callable[[str], None] = print) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Import new crawled documents. Returns (stats, [(document_id, language), ...] newly imported)."""
    if not platform_db.exists():
        raise FileNotFoundError(f"crawler database not found: {platform_db}")
    con = sqlite3.connect(platform_db)
    con.row_factory = sqlite3.Row
    sql = "SELECT * FROM documents WHERE download_status = 'downloaded' AND duplicate_of_id IS NULL"
    params: list = []
    if state:
        sql += " AND state = ?"
        params.append({v.value: k for k, v in STATE_MAP.items()}[state])
    rows = con.execute(sql + " ORDER BY publication_date DESC", params).fetchall()

    existing = {d.sha256 for d in load_corpus(corpus).values()} if corpus.exists() else set()
    stats = {"imported": 0, "already_present": 0, "skipped_needs_ocr": 0, "skipped_no_text": 0, "missing_file": 0, "failed": 0}
    ocr_cache: dict[str, TesseractOcr | None] = {}
    imported: list[tuple[str, str]] = []
    for row in rows:
        if limit and stats["imported"] >= limit:
            break
        if row["pdf_sha256"] in existing:
            stats["already_present"] += 1
            continue
        pdf_path = objects / row["object_storage_key"]
        if not pdf_path.is_file():
            stats["missing_file"] += 1
            continue
        pdf = pdf_path.read_bytes()
        if hashlib.sha256(pdf).hexdigest() != row["pdf_sha256"]:
            log(f"! checksum mismatch, skipped: {pdf_path}")
            stats["missing_file"] += 1
            continue
        entry = entry_for(row)
        forced = unusable_pages(con, row["id"])
        # Always provide OCR when installed: build_document only uses it for pages without a usable
        # text layer (scanned pages, or pages the crawler flagged). The crawler's own OCR text is not
        # in the PDF, so a scan the crawler already OCR'd still needs OCR here.
        langs = OCR_LANGS[entry.language.value]
        if langs not in ocr_cache:
            try:
                ocr_cache[langs] = TesseractOcr(cmd=require_languages(langs))
            except OcrUnavailable as exc:
                log(f"! OCR not available for {langs}: {exc}")
                ocr_cache[langs] = None
        ocr = ocr_cache[langs]
        if ocr is None and forced:
            stats["skipped_needs_ocr"] += 1
            continue
        log(f"→ {entry.id}  {entry.title[:70]}  (OCR pages: {sorted(forced) or 'scanned only'})")
        try:
            doc = build_document(entry, pdf, row["pdf_sha256"], datetime.now(timezone.utc), ocr, force_ocr_pages=forced)
        except Exception as exc:  # one bad PDF must not stop the whole import; it is retried next run
            log(f"! failed, skipped: {entry.id}: {type(exc).__name__}: {exc}")
            stats["failed"] += 1
            continue
        if not any(p["origin"] != "portal_metadata" for p in doc.passages):
            stats["skipped_no_text"] += 1
            continue
        save(doc, corpus)
        render_page_images(pdf, corpus / entry.id)
        existing.add(row["pdf_sha256"])
        imported.append((entry.id, entry.language.value))
        stats["imported"] += 1

    return stats, imported
