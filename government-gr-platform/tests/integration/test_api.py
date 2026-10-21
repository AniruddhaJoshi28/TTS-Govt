from __future__ import annotations

import datetime as dt
import hashlib

import pytest
from fastapi.testclient import TestClient

from core.database.session import session_scope
from core.models import CrawlRun, Document, DocumentPage
from core.storage import get_store, original_key
from services.discovery.pipeline import sync_sources
from tests.conftest import make_pdf

TITLES = {
    "maharashtra": ("शासन निर्णय: ग्रामीण रस्ते दुरुस्ती", "mr", "mh_gr_portal"),
    "madhya_pradesh": ("दिव्यांगजन के रिक्त पदों की पूर्ति के संबंध में", "hi", "mp_socialjustice_circulars"),
    "odisha": ("ଅନୁସୂଚିତ ଜନଜାତି ଛାତ୍ରାବାସ ସଂକଳ୍ପ", "or", "od_stsc_resolutions"),
}


@pytest.fixture
def api(tmp_path):
    from apps.api.main import app

    with session_scope() as s:
        sync_sources(s)
        for i, (state, (title, lang, source)) in enumerate(TITLES.items()):
            pdf = make_pdf(tmp_path / f"{state}.pdf", [f"Body text {state}"])
            sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
            get_store().put_file(original_key(sha), pdf)
            doc = Document(source_id=source, canonical_id=f"id-{state}", state=state, department="Dept", document_type="resolution",
                           document_number=f"NUM-{i}", title=title, publication_date=dt.date(2026, 10, 1 + i), language=lang,
                           original_url=f"https://example.gov.in/{state}.pdf", canonical_url=f"https://example.gov.in/{state}.pdf",
                           pdf_sha256=sha, object_storage_key=original_key(sha), download_status="downloaded", extraction_status="done")
            s.add(doc)
            s.flush()
            s.add(DocumentPage(document_id=doc.id, page_number=1, text=f"{title} — पृष्ठ पाठ unique{i}", extraction_method="pymupdf", char_count=10))
        s.add(CrawlRun(source_id="od_stsc_resolutions", mode="incremental", status="completed"))
    return TestClient(app)


def test_health_and_sources(api):
    assert api.get("/health").json()["documents"] == 3
    sources = api.get("/sources").json()
    assert {s["id"] for s in sources} >= {"mh_gr_portal", "od_stsc_resolutions", "mp_socialjustice_circulars"}
    assert api.get("/sources/od_cabinet").json()["audit_status"] == "UNAVAILABLE"
    assert api.get("/sources/nope").status_code == 404


@pytest.mark.parametrize("state", list(TITLES))
def test_unicode_preserved_through_db_and_api(api, state):
    body = api.get("/documents", params={"state": state}).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == TITLES[state][0]
    assert body["items"][0]["language"] == TITLES[state][1]


def test_filters_and_pagination(api):
    assert api.get("/documents", params={"date_from": "2026-10-02"}).json()["total"] == 2
    assert api.get("/documents", params={"language": "or"}).json()["total"] == 1
    assert api.get("/documents", params={"document_number": "NUM-1"}).json()["total"] == 1
    page = api.get("/documents", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and len(page["items"]) == 1


def test_search_in_page_text_with_snippet(api):
    res = api.get("/documents/search", params={"q": "unique2"}).json()
    assert res["total"] == 1 and res["items"][0]["page_number"] == 1
    assert "unique2" in res["items"][0]["snippet"]
    assert api.get("/documents/search", params={"q": "ग्रामीण"}).json()["total"] == 1


def test_document_detail_pages_and_download(api):
    item = api.get("/documents", params={"state": "odisha"}).json()["items"][0]
    detail = api.get(f"/documents/{item['id']}").json()
    assert detail["provenance"]["original_url"] == "https://example.gov.in/odisha.pdf"
    pages = api.get(f"/documents/{item['id']}/pages").json()
    assert pages[0]["page_number"] == 1
    dl = api.get(f"/documents/{item['id']}/download")
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF-")
    assert hashlib.sha256(dl.content).hexdigest() == item["pdf_sha256"] == dl.headers["x-content-sha256"]


def test_crawl_runs(api):
    runs = api.get("/crawl/runs").json()
    assert runs["total"] == 1
    assert api.get(f"/crawl/runs/{runs['items'][0]['id']}").json()["status"] == "completed"


def test_admin_endpoints_require_auth(api, monkeypatch):
    calls = []
    monkeypatch.setattr("services.discovery.pipeline.run_crawl", lambda *a, **k: calls.append((a, k)))
    payload = {"source_id": "od_stsc_resolutions", "max_pages": 1}
    assert api.post("/crawl/start", json=payload).status_code == 401
    assert api.post("/crawl/start", json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = api.post("/crawl/start", json=payload, headers={"Authorization": "Bearer test-admin-token"})
    assert ok.status_code == 202 and ok.json()["mode"] == "incremental"
    bf = api.post("/crawl/backfill", json=payload, headers={"Authorization": "Bearer test-admin-token"})
    assert bf.status_code == 202 and bf.json()["mode"] == "backfill"
    assert [c[1]["mode"] for c in calls] == ["incremental", "backfill"]
    blocked = api.post("/crawl/start", json={"source_id": "od_cabinet"}, headers={"Authorization": "Bearer test-admin-token"})
    assert blocked.status_code == 409


def test_metrics(api):
    assert "gr_http_requests_total" in api.get("/metrics").text
