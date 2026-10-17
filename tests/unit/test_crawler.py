import pytest
import requests

from services.crawler.fetcher import Fetcher, SourceNotCrawlable
from services.crawler.run import crawl
from services.document_ingestion.store import DocumentStore
from services.source_registry.registry import load_sources
from tests.helpers import FakeResponse, FakeSession, crawlable_source

BASE = "https://gr.example.gov.in"
URL = f"{BASE}/gr/1.pdf"


def fetcher_for(script, **kw):
    return Fetcher(FakeSession(script), sleep=lambda s: None, **kw)


def test_refuses_unverified_sources():
    src = load_sources()[0]
    with pytest.raises(SourceNotCrawlable):
        fetcher_for({}).fetch(src, str(src.base_url))


def test_refuses_off_source_host():
    r = fetcher_for({}).fetch(crawlable_source(), "https://evil.example.com/x.pdf")
    assert not r.ok and "off-source" in r.error


def test_refuses_redirect_off_source():
    f = fetcher_for({URL: [FakeResponse("https://mirror.example.com/1.pdf", content=b"%PDF")]})
    r = f.fetch(crawlable_source(), URL)
    assert not r.ok and "redirected" in r.error


def test_retries_transient_errors_then_succeeds():
    f = fetcher_for({URL: [requests.Timeout("slow"), FakeResponse(URL, 503), FakeResponse(URL, content=b"%PDF ok")]})
    r = f.fetch(crawlable_source(), URL)
    assert r.ok and r.content == b"%PDF ok"


def test_gives_up_after_bounded_attempts():
    f = fetcher_for({URL: [FakeResponse(URL, 503)] * 3}, max_attempts=3)
    r = f.fetch(crawlable_source(), URL)
    assert not r.ok and r.retryable
    assert len(f.session.calls) == 3


def test_404_is_not_retried():
    f = fetcher_for({URL: [FakeResponse(URL, 404)]})
    r = f.fetch(crawlable_source(), URL)
    assert not r.ok and not r.retryable


def test_detects_partial_download():
    resp = FakeResponse(URL, content=b"%PDF trunc", headers={"Content-Length": "9999"})
    f = fetcher_for({URL: [resp]}, max_attempts=1)
    r = f.fetch(crawlable_source(), URL)
    assert not r.ok and "partial" in r.error


def test_enforces_size_limit():
    f = fetcher_for({URL: [FakeResponse(URL, content=b"x" * 100)]}, max_bytes=10)
    r = f.fetch(crawlable_source(), URL)
    assert not r.ok and "size" in r.error


def test_rate_limits_per_host():
    waits = []
    session = FakeSession({URL: [FakeResponse(URL, content=b"a")], f"{BASE}/2.pdf": [FakeResponse(f"{BASE}/2.pdf", content=b"b")]})
    f = Fetcher(session, sleep=waits.append, clock=lambda: 0.0, min_interval=2.0)
    f.fetch(crawlable_source(), URL)
    f.fetch(crawlable_source(), f"{BASE}/2.pdf")
    assert waits == [2.0]


def test_crawl_report_and_retry_of_failed_url(tmp_path):
    store = DocumentStore(tmp_path)
    ok_url = f"{BASE}/ok.pdf"
    f = fetcher_for({ok_url: [FakeResponse(ok_url, content=b"%PDF a")], URL: [FakeResponse(URL, 503)]}, max_attempts=1)
    report = crawl(crawlable_source(), [ok_url, URL], f, store)
    assert report.status == "partial"
    assert report.counts == {"new": 1, "failed": 1}
    store.close()
