"""End-to-end pipeline tests against a mocked Odisha Drupal portal (respx)."""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select

from core.database.session import session_scope
from core.models import CrawlCheckpoint, CrawlRun, DeadLetter, Document, DocumentRelationship, DocumentVersion
from core.storage import get_store
from services.discovery import pipeline
from tests.conftest import make_pdf

BASE = "https://stsc.odisha.gov.in/en/resolutions-circulars-all-data"
HOST = "https://stsc.odisha.gov.in"
SOURCE = "od_stsc_resolutions"


def listing_html(rows: list[tuple[str, str, str, str]], page: int, has_next: bool) -> str:
    trs = "".join(
        f"""<tr><td class="views-field views-field-counter">{i}</td>
        <td class="views-field views-field-title">{title}</td>
        <td class="views-field views-field-field-letter-number">{num}</td>
        <td class="views-field views-field-field-date">{date}</td>
        <td class="views-field views-field-nothing"><a href="{href}">Download(10 KB)</a></td></tr>"""
        for i, (title, num, date, href) in enumerate(rows, 1)
    )
    pager = f'<ul class="pager"><li class="pager__item--next"><a href="?page={page + 1}">Next</a></li></ul>' if has_next else ""
    return f'<html><body><table class="views-table"><thead><tr><th>T</th></tr></thead><tbody>{trs}</tbody></table>{pager}</body></html>'


def page_url(n: int) -> str:
    return BASE if n == 0 else f"{BASE}?page={n}"


class Site:
    """A tiny fake portal: pages of rows, and PDF bodies by path."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.pages: list[list[tuple[str, str, str, str]]] = []
        self.pdfs: dict[str, bytes] = {}
        self.pdf_status: dict[str, int] = {}
        self.page_status: dict[int, int] = {}
        self.page_hits: list[int] = []

    def add_doc(self, page: int, title: str, num: str, date: str, name: str, text: str | None = None, body: bytes | None = None):
        while len(self.pages) <= page:
            self.pages.append([])
        path = f"/sites/default/files/2026-10/{name}.pdf"
        self.pages[page].append((title, num, date, path))
        self.pdfs[path] = body or make_pdf(self.tmp / f"{name}.pdf", [text or f"{title} official text body for testing extraction quality."]).read_bytes()
        return path

    def mount(self, router: respx.MockRouter):
        def listing(request: httpx.Request):
            n = int(request.url.params.get("page", 0))
            self.page_hits.append(n)
            status = self.page_status.get(n, 200)
            if status != 200:
                return httpx.Response(status)
            return httpx.Response(200, text=listing_html(self.pages[n], n, n + 1 < len(self.pages)))

        def pdf(request: httpx.Request):
            path = request.url.path
            if path in self.pdf_status:
                return httpx.Response(self.pdf_status[path])
            body = self.pdfs[path]
            etag = f'"{hash(body) & 0xFFFFFF:x}"'
            if request.headers.get("if-none-match") == etag:
                return httpx.Response(304)
            return httpx.Response(200, content=body, headers={"content-type": "application/pdf", "etag": etag,
                                                              "content-length": str(len(body))})

        router.get(url__startswith=BASE).mock(side_effect=listing)
        router.get(url__regex=rf"{HOST}/sites/default/files/.*").mock(side_effect=pdf)


@pytest.fixture
def site(tmp_path):
    s = Site(tmp_path)
    with respx.mock(assert_all_called=False) as router:
        s.mount(router)
        yield s


def docs() -> list[Document]:
    with session_scope() as s:
        return list(s.scalars(select(Document).order_by(Document.document_number)))


def run_of(run_id: str) -> CrawlRun:
    with session_scope() as s:
        return s.get(CrawlRun, run_id)


def test_end_to_end_crawl_download_extract_with_provenance(site):
    site.add_doc(0, "Resolution on tribal hostels", "101", "01-10-2026", "a")
    site.add_doc(0, "Circular regarding scholarships", "102", "02-10-2026", "b")
    site.add_doc(1, "Notification on reservation", "103", "03-10-2026", "c")
    run_id = pipeline.run_crawl(SOURCE, "incremental")
    run = run_of(run_id)
    assert (run.status, run.pages_fetched, run.documents_discovered, run.documents_downloaded) == ("completed", 2, 3, 3)
    d = docs()
    assert [x.document_type for x in d] == ["resolution", "circular", "notification"]
    first = d[0]
    assert first.download_status == "downloaded" and first.extraction_status == "done"
    assert first.listing_url == BASE
    assert first.original_url == f"{HOST}/sites/default/files/2026-10/a.pdf"
    assert first.http_etag and first.pdf_sha256 and len(first.pdf_sha256) == 64
    assert get_store().get_bytes(first.object_storage_key) == site.pdfs["/sites/default/files/2026-10/a.pdf"]
    with session_scope() as s:
        doc = s.get(Document, first.id)
        assert "tribal hostels" in doc.pages[0].text
        assert [v.change_type for v in doc.versions] == ["discovered", "initial_download"]


def test_duplicate_pdf_detection(site, tmp_path):
    same = make_pdf(tmp_path / "same.pdf", ["Identical binary published at two URLs."]).read_bytes()
    site.add_doc(0, "Resolution copy one", "201", "01-10-2026", "dup1", body=same)
    site.add_doc(0, "Resolution copy two", "202", "01-10-2026", "dup2", body=same)
    site.add_doc(0, "Resolution copy one", "203", "05-10-2026", "same-title-different-binary")
    pipeline.run_crawl(SOURCE, "incremental")
    d = {x.document_number: x for x in docs()}
    assert d["202"].duplicate_of_id == d["201"].id
    assert d["203"].duplicate_of_id is None  # identical title is NOT a duplicate
    with session_scope() as s:
        rel = s.scalars(select(DocumentRelationship)).one()
        assert rel.relation_type == "duplicate_binary" and rel.evidence["sha256"] == d["201"].pdf_sha256
    assert d["201"].object_storage_key == d["202"].object_storage_key


def test_incremental_update_detection_and_early_stop(site):
    for p in range(4):
        site.add_doc(p, f"Resolution page {p}", f"30{p}", "01-09-2026", f"p{p}")
    pipeline.run_crawl(SOURCE, "incremental")
    site.page_hits.clear()
    site.pages[0].insert(0, ("Resolution brand new", "399", "20-10-2026", "/sites/default/files/2026-10/new.pdf"))
    site.pdfs["/sites/default/files/2026-10/new.pdf"] = make_pdf(site.tmp / "new.pdf", ["new doc"]).read_bytes()
    run = run_of(pipeline.run_crawl(SOURCE, "incremental"))
    assert run.documents_new == 1 and run.documents_downloaded == 1
    assert site.page_hits == [0, 1, 2]  # page 0 has a new doc; stops after 2 fully-known pages
    new = [x for x in docs() if x.document_number == "399"][0]
    assert new.publication_date.isoformat() == "2026-10-20" and new.first_seen_at.date() != new.publication_date


def test_document_version_changes(site, tmp_path):
    path = site.add_doc(0, "Resolution amended file", "401", "01-10-2026", "v")
    pipeline.run_crawl(SOURCE, "incremental")
    original_sha = docs()[0].pdf_sha256
    # Unchanged binary: conditional GET -> 304, no new version.
    run = run_of(pipeline.run_crawl(SOURCE, "incremental", recheck_existing=True))
    assert run.documents_changed == 0
    # Publisher silently replaces the PDF at the same URL.
    site.pdfs[path] = make_pdf(tmp_path / "v2.pdf", ["Corrigendum: replaced resolution text."]).read_bytes()
    run = run_of(pipeline.run_crawl(SOURCE, "incremental", recheck_existing=True))
    assert run.documents_changed == 1
    doc = docs()[0]
    assert doc.pdf_sha256 != original_sha
    with session_scope() as s:
        versions = s.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                             .order_by(DocumentVersion.version_number)).all()
        assert [v.change_type for v in versions] == ["discovered", "initial_download", "binary_changed"]
        assert versions[-1].metadata_snapshot["previous_sha256"] == original_sha
    # Both binaries are retained (write-once storage).
    assert get_store().exists(f"originals/{original_sha[:2]}/{original_sha}.pdf")


def test_metadata_change_creates_version(site):
    site.add_doc(0, "Resolution original title", "501", "01-10-2026", "m")
    pipeline.run_crawl(SOURCE, "incremental", download=False)
    title, num, date, href = site.pages[0][0]
    site.pages[0][0] = ("Resolution corrected title", num, date, href)
    run = run_of(pipeline.run_crawl(SOURCE, "incremental", download=False))
    assert run.documents_changed == 1
    with session_scope() as s:
        v = s.scalars(select(DocumentVersion).where(DocumentVersion.change_type == "metadata_changed")).one()
        assert v.metadata_snapshot["changes"]["title"] == {"old": "Resolution original title", "new": "Resolution corrected title"}


def test_backfill_checkpoint_recovery(site):
    for p in range(3):
        site.add_doc(p, f"Resolution archive {p}", f"60{p}", "01-01-2020", f"arch{p}")
    site.page_status[1] = 503  # page 1 keeps failing -> crawl interrupted
    run = run_of(pipeline.run_crawl(SOURCE, "backfill", download=False))
    assert run.status == "failed" and run.errors[0]["stage"] == "discovery"
    with session_scope() as s:
        cp = s.scalars(select(CrawlCheckpoint).where(CrawlCheckpoint.source_id == SOURCE)).one()
        assert cp.state == {"page": 1} and not cp.completed
    site.page_status.clear()
    site.page_hits.clear()
    run = run_of(pipeline.run_crawl(SOURCE, "backfill", download=False))
    assert run.status == "completed"
    assert site.page_hits == [1, 2]  # resumed; page 0 not re-fetched
    assert len(docs()) == 3
    with session_scope() as s:
        assert s.scalars(select(CrawlCheckpoint)).one().completed


def test_download_403_goes_to_dead_letter(site):
    path = site.add_doc(0, "Resolution restricted", "701", "01-10-2026", "forbidden")
    site.add_doc(0, "Resolution ok", "702", "01-10-2026", "fine")
    site.pdf_status[path] = 403
    run = run_of(pipeline.run_crawl(SOURCE, "incremental"))
    assert run.status == "partial" and run.documents_failed == 1 and run.documents_downloaded == 1
    d = {x.document_number: x for x in docs()}
    assert d["701"].download_status == "dead" and "AccessDenied" in d["701"].download_error
    with session_scope() as s:
        dl = s.scalars(select(DeadLetter)).one()
        assert dl.kind == "download" and dl.url.endswith("forbidden.pdf")


def test_transient_download_failure_is_retryable(site):
    path = site.add_doc(0, "Resolution flaky", "801", "01-10-2026", "flaky")
    site.pdf_status[path] = 503
    pipeline.run_crawl(SOURCE, "incremental")
    assert docs()[0].download_status == "failed"
    del site.pdf_status[path]
    assert pipeline.download_document(docs()[0].id) == "downloaded"


def test_invalid_pdf_rejected_in_pipeline(site):
    site.add_doc(0, "Resolution broken file", "901", "01-10-2026", "broken", body=b"%PDF-1.4\n" + b"garbage" * 100)
    pipeline.run_crawl(SOURCE, "incremental")
    d = docs()[0]
    assert d.download_status == "dead" and "InvalidPDFError" in d.download_error and d.object_storage_key is None


def test_database_transaction_failure_rolls_back(site, monkeypatch):
    site.add_doc(0, "Resolution one", "1001", "01-10-2026", "t1")
    site.add_doc(0, "Resolution two", "1002", "01-10-2026", "t2")
    real = pipeline.upsert_discovered
    calls = {"n": 0}

    def flaky(session, item, run_id):
        calls["n"] += 1
        doc = real(session, item, run_id)
        if calls["n"] == 2:
            raise RuntimeError("simulated DB failure after insert")
        return doc

    monkeypatch.setattr(pipeline, "upsert_discovered", flaky)
    run = run_of(pipeline.run_crawl(SOURCE, "incremental", download=False))
    assert run.status == "failed" and "simulated DB failure" in run.errors[0]["error"]
    assert [x.document_number for x in docs()] == ["1001"]  # second insert rolled back
    with session_scope() as s:
        assert len(s.scalars(select(DocumentVersion)).all()) == 1  # no orphan version rows


def test_ocr_fallback_on_scanned_pages(site, tmp_path, monkeypatch):
    from services import ocr

    scanned = make_pdf(tmp_path / "scan.pdf", ["Digital first page text for a government resolution document."], blank_pages=1).read_bytes()
    site.add_doc(0, "Resolution scanned annexure", "1101", "01-10-2026", "scan", body=scanned)
    calls = {}

    def fake_ocr(src, pages, language, state):
        calls["pages"], calls["state"] = pages, state
        return make_pdf(tmp_path / "ocr_out.pdf", ["page one", "OCR recovered annexure text of the scanned government page."])

    monkeypatch.setattr(ocr, "run_ocrmypdf", fake_ocr)
    monkeypatch.setenv("GR_OCR_ENABLED", "true")
    from core.config.settings import get_settings

    get_settings.cache_clear()
    pipeline.run_crawl(SOURCE, "incremental")
    d = docs()[0]
    assert calls == {"pages": [2], "state": "odisha"}
    assert d.extraction_status == "done"
    with session_scope() as s:
        doc = s.get(Document, d.id)
        assert [p.extraction_method for p in doc.pages] == ["pymupdf", "ocr:tesseract"]
        assert doc.pages[1].diagnostics["text_layer_reason"] == "no_text_layer"
        derived = doc.raw_metadata["extraction"]["derived_ocr_key"]
    assert derived.startswith("derived/ocr/") and get_store().exists(derived)
    assert get_store().get_bytes(d.object_storage_key) == scanned  # original untouched


def test_ocr_unavailable_marks_needs_ocr(site, tmp_path, monkeypatch):
    monkeypatch.setenv("GR_OCR_ENABLED", "true")
    from core.config.settings import get_settings
    from services import ocr

    get_settings.cache_clear()
    monkeypatch.setattr(ocr, "ocr_available", lambda: {"ocrmypdf": False, "tesseract": False})
    site.add_doc(0, "Resolution scan only", "1201", "01-10-2026", "scanonly",
                 body=make_pdf(tmp_path / "s.pdf", ["x"], blank_pages=2).read_bytes())
    pipeline.run_crawl(SOURCE, "incremental")
    d = docs()[0]
    assert d.extraction_status == "needs_ocr"
    assert "ocr_unavailable" in d.raw_metadata["extraction"]
