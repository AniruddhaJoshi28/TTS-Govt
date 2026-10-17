"""Synthetic test doubles. No real government documents are used in tests."""

from services.source_registry.registry import Source


def crawlable_source(base_url: str = "https://gr.example.gov.in") -> Source:
    return Source.model_validate(
        dict(id="test-src", state="MH", name="Test source", base_url=base_url, document_types=["GR"],
             languages=["mr"], crawl_method="http", verified=True, terms_reviewed=True)
    )


class FakeResponse:
    def __init__(self, url, status=200, content=b"", headers=None):
        self.url = url
        self.status_code = status
        self._content = content
        self.headers = {"Content-Length": str(len(content)), **(headers or {})}

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def close(self):
        pass


class FakeSession:
    """Returns queued responses (or raises queued exceptions) per URL, in order."""

    def __init__(self, script: dict):
        self.script = {url: list(items) for url, items in script.items()}
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        item = self.script[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_pdf(text: str | None) -> bytes:
    """Minimal one-page PDF. ``text=None`` gives a page with no text (like a scan)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)
