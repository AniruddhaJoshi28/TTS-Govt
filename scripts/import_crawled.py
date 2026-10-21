"""Import documents archived by government-gr-platform (the crawler) into the assistant corpus.

    python scripts/import_crawled.py                       # all downloaded docs not yet imported
    python scripts/import_crawled.py --state MH --limit 20
    python scripts/import_crawled.py --reload-url http://127.0.0.1:8000/api/v1/reload

The crawler's SQLite DB and local object store are read directly (no platform imports: both projects
have a top-level ``services`` package). Pages the crawler flagged as unusable (no text layer, broken
ToUnicode maps, Devanagari glyph-order errors) are OCR'd instead of trusting the embedded text.
Documents that need OCR are skipped when Tesseract or its language data is missing, rather than
being imported with corrupt or empty text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.api.envelope import Language, State  # noqa: E402
from services.document_ingestion.corpus import build_document, load_corpus, render_page_images, save  # noqa: E402
from services.document_ingestion.manifest import DocumentEntry, FetchSpec  # noqa: E402
from services.pdf_ocr.ocr import OCR_LANGS, OcrUnavailable, TesseractOcr, require_languages  # noqa: E402

PLATFORM = ROOT / "government-gr-platform"
STATE_MAP = {"maharashtra": State.MAHARASHTRA, "madhya_pradesh": State.MADHYA_PRADESH, "odisha": State.ODISHA}
DEFAULT_LANG = {"maharashtra": "mr", "madhya_pradesh": "hi", "odisha": "or"}


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
    issued = date.fromisoformat(row["publication_date"]) if row["publication_date"] else date.today()
    return DocumentEntry(
        id=corpus_id(row), state=STATE_MAP[row["state"]], language=Language(lang),
        document_type=row["document_type"], issued=issued,
        # No machine translation: the English fields repeat the official text rather than invent one.
        department=row["department"] or "", department_en=row["department"] or "",
        title=row["title"], title_en=row["title"],
        url=row["original_url"], listing_url=row["listing_url"] or row["original_url"],
        fetch=FetchSpec(method="crawler", path=row["object_storage_key"]), portal_metadata=meta,
    )


def warm_summaries(app_url: str, docs: list[tuple[str, str]]) -> None:
    """Generate each new GR's summary in its own language now, so the first click in the UI is a cache hit."""
    for doc_id, lang in docs:
        body = json.dumps({"document_id": doc_id, "language": lang}).encode()
        req = urllib.request.Request(f"{app_url.rstrip('/')}/api/v1/summaries", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-API-Key": os.environ.get("API_KEY", "")})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                status = json.loads(resp.read()).get("data", {}).get("status")
            print(f"  summary {doc_id} ({lang}): {status}")
        except Exception as exc:  # model down etc.: the UI will generate it on demand instead
            print(f"  summary {doc_id} ({lang}) not pre-generated: {exc}", file=sys.stderr)
            return


def reload_app(url: str) -> None:
    req = urllib.request.Request(url, method="POST", headers={"X-API-Key": os.environ.get("API_KEY", "")})
    with urllib.request.urlopen(req, timeout=60) as resp:
        print("app reloaded:", resp.read().decode()[:200])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform-db", type=Path, default=PLATFORM / "data" / "gr_platform.sqlite3")
    ap.add_argument("--objects", type=Path, default=PLATFORM / "data" / "objects")
    ap.add_argument("--corpus", type=Path, default=Path(os.environ.get("CORPUS_DIR", ROOT / "data" / "corpus")))
    ap.add_argument("--state", choices=[s.value for s in STATE_MAP.values()])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reload-url", help="POST here afterwards so a running app picks up the new documents")
    ap.add_argument("--warm-url", help="app base URL: pre-generate summaries of newly imported GRs")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if not args.platform_db.exists():
        print(f"crawler database not found: {args.platform_db}", file=sys.stderr)
        return 1
    con = sqlite3.connect(args.platform_db)
    con.row_factory = sqlite3.Row
    sql = "SELECT * FROM documents WHERE download_status = 'downloaded' AND duplicate_of_id IS NULL"
    params: list = []
    if args.state:
        sql += " AND state = ?"
        params.append({v.value: k for k, v in STATE_MAP.items()}[args.state])
    rows = con.execute(sql + " ORDER BY publication_date DESC", params).fetchall()

    existing = {d.sha256 for d in load_corpus(args.corpus).values()} if args.corpus.exists() else set()
    stats = {"imported": 0, "already_present": 0, "skipped_needs_ocr": 0, "skipped_no_text": 0, "missing_file": 0}
    ocr_cache: dict[str, TesseractOcr | None] = {}
    imported: list[tuple[str, str]] = []
    for row in rows:
        if args.limit and stats["imported"] >= args.limit:
            break
        if row["pdf_sha256"] in existing:
            stats["already_present"] += 1
            continue
        pdf_path = args.objects / row["object_storage_key"]
        if not pdf_path.is_file():
            stats["missing_file"] += 1
            continue
        pdf = pdf_path.read_bytes()
        if hashlib.sha256(pdf).hexdigest() != row["pdf_sha256"]:
            print(f"! checksum mismatch, skipped: {pdf_path}", file=sys.stderr)
            stats["missing_file"] += 1
            continue
        entry = entry_for(row)
        forced = unusable_pages(con, row["id"])
        ocr = None
        if forced or row["extraction_status"] in ("needs_ocr", "pending", "failed"):
            langs = OCR_LANGS[entry.language.value]
            if langs not in ocr_cache:
                try:
                    ocr_cache[langs] = TesseractOcr(cmd=require_languages(langs))
                except OcrUnavailable as exc:
                    print(f"! OCR not available for {langs}: {exc}", file=sys.stderr)
                    ocr_cache[langs] = None
            ocr = ocr_cache[langs]
            if ocr is None and forced:
                stats["skipped_needs_ocr"] += 1
                continue
        print(f"→ {entry.id}  {entry.title[:70]}  (OCR pages: {sorted(forced) or 'scanned only'})")
        doc = build_document(entry, pdf, row["pdf_sha256"], datetime.now(timezone.utc), ocr, force_ocr_pages=forced)
        if not any(p["origin"] != "portal_metadata" for p in doc.passages):
            stats["skipped_no_text"] += 1
            continue
        save(doc, args.corpus)
        render_page_images(pdf, args.corpus / entry.id)
        existing.add(row["pdf_sha256"])
        imported.append((entry.id, entry.language.value))
        stats["imported"] += 1

    print(json.dumps(stats, indent=2))
    if args.reload_url and stats["imported"]:
        reload_app(args.reload_url)
    if args.warm_url and imported:
        warm_summaries(args.warm_url, imported)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
