"""Download (if needed), store, extract/OCR and index the demo documents.

    python scripts/build_corpus.py            # use PDFs already in data/raw/
    python scripts/build_corpus.py --download # fetch missing PDFs from the official sources

Originals go through the versioned DocumentStore (data/store/), so every
build keeps provenance and revision history. Output: data/corpus/<id>/.
"""

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.document_ingestion.corpus import build_document, load_review, render_page_images, save  # noqa: E402
from services.document_ingestion.download import download  # noqa: E402
from services.document_ingestion.manifest import load_manifest  # noqa: E402
from services.document_ingestion.store import DocumentStore  # noqa: E402
from services.pdf_ocr.ocr import OcrUnavailable, TesseractOcr  # noqa: E402

RAW = ROOT / "data" / "raw"
STORE = ROOT / "data" / "store"
CORPUS = ROOT / "data" / "corpus"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="fetch PDFs missing from data/raw/")
    ap.add_argument("--only", help="build a single document id")
    args = ap.parse_args()

    try:
        ocr = TesseractOcr()
    except OcrUnavailable as exc:
        print(f"OCR unavailable ({exc}); scanned pages will have no text", file=sys.stderr)
        ocr = None

    RAW.mkdir(parents=True, exist_ok=True)
    store = DocumentStore(STORE)
    for entry in load_manifest():
        if args.only and entry.id != args.only:
            continue
        raw = RAW / f"{entry.id}.pdf"
        if not raw.exists():
            if not args.download:
                print(f"skip {entry.id}: {raw} missing (use --download)")
                continue
            print(f"download {entry.id} …")
            raw.write_bytes(download(entry))
        pdf = raw.read_bytes()
        ingested = store.ingest(entry.state.value, str(entry.url), pdf)
        sha = hashlib.sha256(pdf).hexdigest()
        version = store.versions(str(entry.url))[-1]
        retrieved = datetime.fromisoformat(version["retrieved_at"]).astimezone(timezone.utc)

        corrections, transcriptions = load_review(entry.id)
        doc = build_document(entry, pdf, sha, retrieved, ocr, corrections, transcriptions)
        pending = sum(1 for t in transcriptions if not t.signed) + sum(1 for c in corrections if not (c.reviewer and c.reviewed_at))
        path = save(doc, CORPUS)
        render_page_images(pdf, CORPUS / entry.id)
        flagged = sum(len(p.untrusted) for p in doc.pages)
        origins = ",".join(sorted({p.origin for p in doc.pages}))
        print(f"{entry.id}: {ingested.status}, {len(doc.pages)} pages ({origins}), "
              f"{len(doc.passages)} passages, {flagged} untrusted numbers, {pending} review items awaiting sign-off "
              f"-> {path.relative_to(ROOT)}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
