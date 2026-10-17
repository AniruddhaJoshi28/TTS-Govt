"""Tracks the plan §4 edge-case matrix. Unimplemented cases show up as skipped."""

from pathlib import Path

import pytest
import yaml

from services.crawler.fetcher import Fetcher
from services.crawler.run import crawl
from services.document_ingestion.store import DocumentStore
from tests.helpers import FakeResponse, FakeSession, crawlable_source

MANIFEST = Path(__file__).parents[2] / "data" / "test_manifests" / "edge_cases.yaml"
CASES = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["cases"]

URL = "https://gr.example.gov.in/gr/1.pdf"


def ec01_source_unavailable_keeps_last_version(tmp_path: Path):
    store = DocumentStore(tmp_path)
    store.ingest("test-src", URL, b"%PDF good version")
    fetcher = Fetcher(FakeSession({URL: [FakeResponse(URL, 503)]}), sleep=lambda s: None, max_attempts=1)

    report = crawl(crawlable_source(), [URL], fetcher, store)

    assert report.status == "failed"
    fresh = store.freshness(URL)
    assert store.read_blob(fresh.sha256) == b"%PDF good version"
    assert fresh.retrieved_at is not None
    assert fresh.verified_fresh is False and "503" in fresh.last_error
    store.close()


def ec02_duplicate_document(tmp_path: Path):
    store = DocumentStore(tmp_path)
    a = store.ingest("test-src", "https://gr.example.gov.in/a.pdf", b"%PDF same")
    b = store.ingest("test-src", "https://gr.example.gov.in/mirror/a.pdf", b"%PDF same")
    assert (a.status, b.status) == ("new", "duplicate")
    assert a.sha256 == b.sha256
    assert store.urls_for(a.sha256) == ["https://gr.example.gov.in/a.pdf", "https://gr.example.gov.in/mirror/a.pdf"]
    assert len(list(store.blob_dir.rglob("*"))) == 2  # one shard dir + one blob
    store.close()


def ec03_revised_pdf_at_same_url(tmp_path: Path):
    store = DocumentStore(tmp_path)
    v1 = store.ingest("test-src", URL, b"%PDF v1")
    v2 = store.ingest("test-src", URL, b"%PDF v2")
    assert v2.status == "revised" and v2.previous_sha256 == v1.sha256
    versions = store.versions(URL)
    assert [v["is_current"] for v in versions] == [0, 1]
    assert store.read_blob(v1.sha256) == b"%PDF v1"
    store.close()


IMPLEMENTED = {
    "EC-01": ec01_source_unavailable_keeps_last_version,
    "EC-02": ec02_duplicate_document,
    "EC-03": ec03_revised_pdf_at_same_url,
}


def test_matrix_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_edge_case(case, tmp_path):
    check = IMPLEMENTED.get(case["id"])
    if check is None:
        pytest.skip(f"pending (workstream {case['workstream']}): {case['scenario']}")
    check(tmp_path)
