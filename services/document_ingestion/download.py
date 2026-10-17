"""Single-document retrieval for manifest entries (not a crawler).

Fetches one named document per call, politely, and refuses anything that is
not a PDF. The MP labour portal serves documents only through its viewer, so
that flow is reproduced step by step: press "View" on the listing, open the
viewer page, follow its PDF link.
"""

import html
import re
import time
from urllib.parse import urljoin

import requests

from services.crawler.fetcher import USER_AGENT
from services.document_ingestion.manifest import DocumentEntry

PAUSE = 3.0


class DownloadError(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _require_pdf(resp: requests.Response) -> bytes:
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF-"):
        raise DownloadError(f"expected a PDF from {resp.url}, got {resp.headers.get('content-type')}")
    return resp.content


def _form_fields(page: str) -> dict[str, str]:
    form = {}
    for tag in re.findall(r"<input[^>]*>", page):
        name = re.search(r'name="([^"]+)"', tag)
        typ = re.search(r'type="([^"]+)"', tag)
        if not name or (typ and typ.group(1) in ("submit", "image", "button")):
            continue
        val = re.search(r'value="([^"]*)"', tag)
        form[name.group(1)] = html.unescape(val.group(1)) if val else ""
    return form


def _mp_labour_dms(s: requests.Session, listing: str, path: str, sleep) -> bytes:
    page = s.get(listing, timeout=60).text
    row = next((r for r in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S) if path in r), None)
    if row is None:
        raise DownloadError(f"{path} is no longer listed on {listing}")
    button = re.search(r'name="([^"]+lnkView)"', row).group(1)
    form = _form_fields(page) | {f"{button}.x": "10", f"{button}.y": "10"}
    sleep(PAUSE)
    posted = s.post(listing, data=form, timeout=60).text
    viewer = re.search(r"window\.open\('([^']+)'", posted)
    if not viewer:
        raise DownloadError("viewer link not found after pressing View")
    sleep(PAUSE)
    viewer_url = urljoin(listing, viewer.group(1))
    viewer_page = s.get(viewer_url, timeout=60).text
    link = re.search(r'href="(ShowPDF\.axd[^"]+)"', viewer_page)
    if not link:
        raise DownloadError("PDF link not found on viewer page")
    sleep(PAUSE)
    return _require_pdf(s.get(urljoin(viewer_url, html.unescape(link.group(1))), timeout=120))


def download(entry: DocumentEntry, sleep=time.sleep) -> bytes:
    s = _session()
    if entry.fetch.method == "direct":
        return _require_pdf(s.get(str(entry.url), timeout=120))
    if entry.fetch.method == "mp_labour_dms":
        return _mp_labour_dms(s, str(entry.listing_url), entry.fetch.path or "", sleep)
    raise DownloadError(f"unknown fetch method {entry.fetch.method!r}")
