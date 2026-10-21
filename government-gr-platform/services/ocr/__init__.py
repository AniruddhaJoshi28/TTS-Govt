"""OCR fallback using OCRmyPDF + Tesseract (self-hosted, Indic language packs).

* Runs only on documents where some pages failed text-layer assessment.
* Never modifies the original: OCRmyPDF writes a *derived* searchable PDF, stored under
  ``derived/ocr/...``; page text is read back from it for the failed pages only.
* Tesseract languages: mar (Marathi), hin (Hindi), ori (Odia), eng. Install packs via the
  Dockerfile (tesseract-ocr-mar, -hin, -ori).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TESSERACT_LANGS = {"mr": "mar+eng", "hi": "hin+eng", "or": "ori+eng", "en": "eng"}
STATE_DEFAULT_LANG = {"maharashtra": "mr", "madhya_pradesh": "hi", "odisha": "or"}


class OCRUnavailable(RuntimeError):
    pass


def ocr_available() -> dict[str, bool]:
    return {"ocrmypdf": shutil.which("ocrmypdf") is not None, "tesseract": shutil.which("tesseract") is not None}


def installed_tesseract_langs() -> set[str]:
    if not shutil.which("tesseract"):
        return set()
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30)
    return {line.strip() for line in out.stdout.splitlines()[1:] if line.strip()}


def lang_spec(language: str | None, state: str | None) -> str:
    lang = language or STATE_DEFAULT_LANG.get(state or "", "en")
    spec = TESSERACT_LANGS.get(lang, "eng")
    installed = installed_tesseract_langs()
    if installed:
        parts = [p for p in spec.split("+") if p in installed]
        spec = "+".join(parts) or "eng"
    return spec


def run_ocrmypdf(src: Path, pages: list[int], language: str | None, state: str | None) -> Path:
    """OCR the given 1-based pages into a new searchable PDF; returns its path."""
    if not ocr_available()["ocrmypdf"]:
        raise OCRUnavailable("ocrmypdf is not installed on this host")
    out = Path(tempfile.mkstemp(suffix=".ocr.pdf")[1])
    cmd = [
        "ocrmypdf", "--force-ocr", "--output-type", "pdf", "--optimize", "0", "--quiet",
        "-l", lang_spec(language, state), "--pages", ",".join(str(p) for p in pages), str(src), str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"ocrmypdf failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return out


def read_pages(path: Path, pages: list[int]) -> dict[int, str]:
    import pymupdf as fitz

    with fitz.open(path) as doc:
        return {p: doc[p - 1].get_text("text") for p in pages if 0 < p <= doc.page_count}
