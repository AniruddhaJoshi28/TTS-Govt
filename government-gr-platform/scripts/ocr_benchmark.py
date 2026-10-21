"""OCR quality benchmark per state/language.

Method: for archived documents whose text layer passed quality checks (ground truth = digital text),
rasterise each page, OCR it with Tesseract, and report character error rate (CER) against the
digital text. This measures OCR quality on real government layouts without manual transcription.

Run on an OCR-capable host (the Docker image ships tesseract + mar/hin/ori packs):

    docker compose run --rm worker python scripts/ocr_benchmark.py --per-state 10
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from core.database.session import session_scope
from core.models import Document, DocumentPage
from core.storage import get_store
from services.metadata import clean_text
from services.ocr import lang_spec


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    ref, hyp = "".join(clean_text(reference).split()), "".join(clean_text(hypothesis).split())
    return levenshtein(ref[:3000], hyp[:3000]) / max(1, len(ref[:3000]))


def ocr_page(pdf: Path, page_no: int, lang: str) -> str:
    import pymupdf

    with pymupdf.open(pdf) as doc, tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "p.png"
        doc[page_no - 1].get_pixmap(dpi=300).save(png)
        out = subprocess.run(["tesseract", str(png), "stdout", "-l", lang], capture_output=True, text=True, timeout=300)
        return out.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-state", type=int, default=5)
    args = ap.parse_args()
    results: dict[str, list[float]] = defaultdict(list)
    with session_scope() as s:
        rows = s.execute(select(Document, DocumentPage).join(DocumentPage).where(
            DocumentPage.extraction_method == "pymupdf", DocumentPage.char_count > 300)).all()
    seen: dict[str, int] = defaultdict(int)
    for doc, page in rows:
        if seen[doc.state] >= args.per_state or not page.diagnostics.get("usable"):
            continue
        seen[doc.state] += 1
        path = get_store().open_path(doc.object_storage_key)
        hyp = ocr_page(path, page.page_number, lang_spec(doc.language, doc.state))
        results[f"{doc.state}/{doc.language}"].append(cer(page.text, hyp))
    print(json.dumps({k: {"pages": len(v), "mean_cer": round(sum(v) / len(v), 4)} for k, v in results.items()}, indent=2))


if __name__ == "__main__":
    main()
