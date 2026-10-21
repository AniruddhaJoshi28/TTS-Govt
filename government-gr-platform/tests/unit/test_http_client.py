"""Retry, rate-limit, access-control and download-safety behaviour of PoliteClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from core.validation import UnsafeURLError
from crawlers.base.http import (
    AccessDenied,
    DownloadTooLarge,
    FetchError,
    NotAPDF,
    PoliteClient,
    RobotsDisallowed,
    parse_retry_after,
)
from tests.conftest import pdf_bytes

HOST = "gr.maharashtra.gov.in"
URL = f"https://{HOST}/page"
PDF_URL = f"https://{HOST}/doc.pdf"


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(sleeps):
    c = PoliteClient([HOST], min_interval=0, max_retries=3, obey_robots=False, sleep=sleeps.append)
    yield c
    c.close()


@respx.mock
def test_retry_on_503_then_success(client, sleeps):
    route = respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, text="ok")])
    assert client.get_text(URL).text == "ok"
    assert route.call_count == 3 and len(sleeps) == 2


@respx.mock
def test_429_honours_retry_after(client, sleeps):
    respx.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")])
    client.get_text(URL)
    assert sleeps == [7.0]


@respx.mock
def test_429_gives_up_after_max_retries(client, sleeps):
    respx.get(URL).mock(return_value=httpx.Response(429))
    with pytest.raises(FetchError) as exc:
        client.get_text(URL)
    assert exc.value.status == 429 and exc.value.retryable
    assert len(sleeps) == 3


@respx.mock
def test_403_is_not_retried(client, sleeps):
    route = respx.get(URL).mock(return_value=httpx.Response(403))
    with pytest.raises(AccessDenied):
        client.get_text(URL)
    assert route.call_count == 1 and sleeps == []


@respx.mock
def test_transport_error_retried(client, sleeps):
    respx.get(URL).mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200, text="ok")])
    assert client.get_text(URL).text == "ok"
    assert len(sleeps) == 1


@respx.mock
def test_redirect_to_foreign_host_rejected(client):
    respx.get(URL).mock(return_value=httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"}))
    with pytest.raises(UnsafeURLError):
        client.get_text(URL)


@respx.mock
def test_redirect_within_allowlist_followed(client):
    respx.get(URL).mock(return_value=httpx.Response(301, headers={"Location": "/other"}))
    respx.get(f"https://{HOST}/other").mock(return_value=httpx.Response(200, text="moved"))
    resp = client.get_text(URL)
    assert resp.text == "moved" and resp.extensions["redirect_hops"] == [f"https://{HOST}/other"]


@respx.mock
def test_robots_disallow_respected(sleeps):
    respx.get(f"https://{HOST}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private/\n",
                                                                             headers={"content-type": "text/plain"}))
    respx.get(URL).mock(return_value=httpx.Response(200, text="ok"))
    c = PoliteClient([HOST], min_interval=0, obey_robots=True, sleep=sleeps.append)
    assert c.get_text(URL).text == "ok"
    with pytest.raises(RobotsDisallowed):
        c.get_text(f"https://{HOST}/private/x")


@respx.mock
def test_robots_403_means_no_rules(sleeps):
    respx.get(f"https://{HOST}/robots.txt").mock(return_value=httpx.Response(403))
    respx.get(URL).mock(return_value=httpx.Response(200, text="ok"))
    c = PoliteClient([HOST], min_interval=0, obey_robots=True, sleep=sleeps.append)
    assert c.get_text(URL).text == "ok"


@respx.mock
def test_download_valid_pdf(client, tmp_path):
    body = pdf_bytes(tmp_path)
    respx.get(PDF_URL).mock(return_value=httpx.Response(200, content=body, headers={
        "content-type": "application/pdf", "etag": '"abc"', "last-modified": "Wed, 21 Oct 2026 05:54:43 GMT",
        "content-length": str(len(body))}))
    res = client.download_pdf(PDF_URL)
    assert res.path.read_bytes() == body and res.etag == '"abc"'
    res.path.unlink()


@respx.mock
def test_download_html_instead_of_pdf_rejected(client):
    respx.get(PDF_URL).mock(return_value=httpx.Response(200, text="<html>error</html>", headers={"content-type": "text/html"}))
    with pytest.raises(NotAPDF):
        client.download_pdf(PDF_URL)


@respx.mock
def test_download_mislabelled_non_pdf_rejected(client):
    respx.get(PDF_URL).mock(return_value=httpx.Response(200, content=b"PK\x03\x04zipdata" * 100,
                                                        headers={"content-type": "application/pdf"}))
    with pytest.raises(NotAPDF):
        client.download_pdf(PDF_URL)


@respx.mock
def test_download_size_cap(client, tmp_path):
    client.max_pdf_bytes = 100
    respx.get(PDF_URL).mock(return_value=httpx.Response(200, content=pdf_bytes(tmp_path), headers={"content-type": "application/pdf"}))
    with pytest.raises(DownloadTooLarge):
        client.download_pdf(PDF_URL)


@respx.mock
def test_download_interrupted_detected(client, tmp_path):
    body = pdf_bytes(tmp_path)

    class Truncating(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:500]
            raise httpx.ReadError("connection reset")

    respx.get(PDF_URL).mock(return_value=httpx.Response(200, stream=Truncating(),
                                                        headers={"content-type": "application/pdf", "content-length": str(len(body))}))
    with pytest.raises(FetchError) as exc:
        client.download_pdf(PDF_URL)
    assert exc.value.retryable
    assert not list(tmp_path.glob("tmp*.pdf"))


@respx.mock
def test_conditional_get_not_modified(client):
    route = respx.get(PDF_URL).mock(return_value=httpx.Response(304))
    res = client.download_pdf(PDF_URL, etag='"abc"', last_modified="Wed, 21 Oct 2026 05:54:43 GMT")
    assert res.not_modified
    assert route.calls.last.request.headers["if-none-match"] == '"abc"'


def test_parse_retry_after():
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
