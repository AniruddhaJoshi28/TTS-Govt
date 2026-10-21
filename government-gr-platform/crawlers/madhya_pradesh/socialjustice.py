"""MP Social Justice & Disabled Persons Welfare Dept (socialjustice.mp.gov.in) — CodeIgniter AJAX listing.

Audit findings (2026-10-21):
* ``/circular`` renders an empty ``#ajaxdata`` container; rows come from
  ``POST /Circular/ajaxPaginationData/<offset>`` with form fields page, cat_id, issed_by, year, sTitle,
  csrf_token_id. The endpoint requires the ``ci_session`` cookie from a prior GET on the *same host*
  (``socialjustice.mp.gov.in``; the ``www.`` host gets a separate session and the POST returns 403).
* Offset pagination in steps of 10 (``searchFilter(10)``, ``searchFilter(20)`` ...).
* Columns: क्रमांक / आदेश क्रमांक / श्रेणी / शीर्षक / को जारी / जारीकर्ता / प्रकाशित तिथि / लिंक.
* PDFs at ``/uploads/files/<name>.pdf`` (file names may contain Devanagari).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from core.schemas import DiscoveredDocument
from core.validation import canonicalize_url
from crawlers.base.adapter import ListingPage, SourceAdapter
from services.metadata import classify_document_type, clean_text, detect_language, parse_date

HOST = "https://socialjustice.mp.gov.in"


def max_offset(soup: BeautifulSoup) -> int:
    offsets = [int(m) for a in soup.find_all("a", onclick=True) for m in re.findall(r"searchFilter\((\d+)\)", a["onclick"])]
    return max(offsets) if offsets else 0


class MPSocialJusticeAdapter(SourceAdapter):
    name = "mp_socialjustice_ajax"

    def initial_state(self, mode: str) -> dict[str, Any]:
        return {"offset": 0}

    def iter_listing_pages(self, state: dict[str, Any], mode: str) -> Iterator[ListingPage]:
        listing_url = f"{HOST}/circular"
        page_size = int(self.options.get("page_size", 10))
        self.client.get_text(listing_url)  # establishes ci_session cookie
        offset = int(state.get("offset", 0))
        page_index = offset // page_size
        while True:
            ajax_url = f"{HOST}/Circular/ajaxPaginationData/{offset}"
            resp = self.client.post_form(
                ajax_url,
                {"page": str(offset), "cat_id": "", "issed_by": "", "year": "", "sTitle": "", "csrf_token_id": ""},
                headers={"Referer": listing_url, "X-Requested-With": "XMLHttpRequest"},
            )
            soup = BeautifulSoup(resp.text, "lxml")
            last_offset = max_offset(soup)
            is_last = offset >= last_offset
            yield ListingPage(url=ajax_url, html=resp.text, page_index=page_index,
                              next_state={"offset": offset + page_size}, is_last=is_last,
                              extra={"listing_url": listing_url, "last_offset": last_offset})
            if is_last:
                return
            offset += page_size
            page_index += 1

    def extract_listing_metadata(self, listing: ListingPage) -> list[dict[str, Any]]:
        soup = BeautifulSoup(listing.html, "lxml")
        rows = []
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            link = tr.find("a", href=True)
            if len(tds) < 8 or link is None:
                continue
            c = [clean_text(td.get_text(" ")) for td in tds]
            rows.append({"serial": c[0], "order_number": c[1], "category": c[2], "title": c[3],
                         "issued_to": c[4], "issued_by": c[5], "published": c[6], "href": link["href"]})
        return rows

    def resolve_document_url(self, row: dict[str, Any], listing: ListingPage) -> str:
        url = urljoin(listing.url, row["href"])
        # Normalise www. -> bare host so both spellings map to one canonical document.
        p = urlsplit(url)
        if p.hostname == "www.socialjustice.mp.gov.in":
            url = url.replace("://www.socialjustice.mp.gov.in", "://socialjustice.mp.gov.in", 1)
        return canonicalize_url(url)

    def normalize_metadata(self, row: dict[str, Any], document_url: str, listing: ListingPage) -> DiscoveredDocument:
        return DiscoveredDocument(
            source_key=self.source.key,
            canonical_id=urlsplit(document_url).path,
            state="madhya_pradesh",
            department=self.source.department,
            document_type=classify_document_type(row["title"], default=self.source.source_type),
            document_number=row["order_number"] or None,
            title=row["title"],
            publication_date=parse_date(row["published"]),
            language=detect_language(row["title"], "madhya_pradesh"),
            document_url=document_url,
            listing_url=listing.extra.get("listing_url"),
            raw={**row, "listing_page": listing.page_index},
        )
