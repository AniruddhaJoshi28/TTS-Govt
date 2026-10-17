"""Tesseract OCR for scanned or badly encoded pages (Workstream B, steps 3, 7).

Uses the ``tessdata_best`` models for Marathi (mar), Hindi (hin) and Odia
(ori), combined with English so embedded English terms survive. Word-level
confidences are kept so critical fields can be gated (see
services/metadata_extraction/critical.py).
"""

import os
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import ImageOps

OCR_LANGS = {"mr": "mar+eng", "hi": "hin+eng", "or": "ori+eng", "en": "eng"}

_WINDOWS_DEFAULTS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR/tesseract.exe",
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
]


class OcrUnavailable(RuntimeError):
    pass


def find_tesseract() -> str:
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit:
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    for path in _WINDOWS_DEFAULTS:
        if path.is_file():
            return str(path)
    raise OcrUnavailable("tesseract not found; install it or set TESSERACT_CMD")


@dataclass(frozen=True)
class OcrWord:
    text: str
    conf: float  # 0–100
    start: int  # character offset in OcrPage.text
    end: int


@dataclass(frozen=True)
class OcrPage:
    page: int
    text: str
    words: list[OcrWord]

    @property
    def mean_conf(self) -> float:
        return sum(w.conf for w in self.words) / len(self.words) if self.words else 0.0


class TesseractOcr:
    def __init__(self, cmd: str | None = None, dpi: int = 300, timeout: float = 300.0):
        self.cmd = cmd or find_tesseract()
        self.dpi = dpi
        self.timeout = timeout

    def page(self, pdf_bytes: bytes, page: int, langs: str) -> OcrPage:
        """OCR one 1-based page of a PDF."""
        doc = pdfium.PdfDocument(pdf_bytes)
        try:
            image = doc[page - 1].render(scale=self.dpi / 72).to_pil()
        finally:
            doc.close()
        image = ImageOps.autocontrast(image.convert("L"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.png"
            image.save(path)
            proc = subprocess.run(
                [self.cmd, str(path), "stdout", "-l", langs, "--psm", "3", "tsv"],
                capture_output=True, timeout=self.timeout, check=False,
            )
        if proc.returncode != 0:
            raise OcrUnavailable(proc.stderr.decode("utf-8", "replace").strip() or "tesseract failed")
        return parse_tsv(page, proc.stdout.decode("utf-8", "replace"))


def parse_tsv(page: int, tsv: str) -> OcrPage:
    """Rebuild text (paragraphs and lines) from Tesseract TSV, keeping word offsets."""
    parts: list[str] = []
    words: list[OcrWord] = []
    pos = 0
    last_par = last_line = None
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = unicodedata.normalize("NFC", cols[11].strip())
        if not text:
            continue
        par, line = (cols[2], cols[3]), (cols[2], cols[3], cols[4])
        if last_line is None:
            sep = ""
        elif par != last_par:
            sep = "\n\n"
        elif line != last_line:
            sep = "\n"
        else:
            sep = " "
        parts.append(sep)
        pos += len(sep)
        words.append(OcrWord(text, float(cols[10]), pos, pos + len(text)))
        parts.append(text)
        pos += len(text)
        last_par, last_line = par, line
    return OcrPage(page, "".join(parts), words)
