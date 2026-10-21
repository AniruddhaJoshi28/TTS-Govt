"""Odisha departmental portals built on the common Odisha Government Drupal template.

Audit findings (2026-10-21) for stsc.odisha.gov.in and agri.odisha.gov.in:
* Listing is a Drupal Views table (``table.views-table``); columns are identified by
  ``views-field-*`` classes, not position (the column order differs between departments):
  ``views-field-title``, ``views-field-field-letter-number``, ``views-field-field-date``,
  link inside ``views-field-nothing``.
* Pagination: ``?page=N`` (0-based), Drupal pager.
* PDFs under ``/sites/default/files/YYYY-MM/<name>.pdf`` on the same host.
* robots.txt returns HTTP 403 (no published rules) → crawl politely at a conservative rate.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from core.schemas import DiscoveredDocument
from core.validation import canonicalize_url
from crawlers.base.adapter import ListingPage, SourceAdapter
from services.metadata import classify_document_type, clean_text, detect_language, parse_date

FIELD_MAP = {
    "views-field-title": "title",
    "views-field-field-letter-number": "letter_number",
    "views-field-field-date": "date",
    "views-field-field-department": "department",
    "views-field-field-category": "category",
}


def page_url(base_url: str, page: int) -> str:
    p = urlsplit(base_url)
    query = re.sub(r"(^|&)page=\d+", "", p.query).strip("&")
    if page > 0:
        query = f"{query}&page={page}" if query else f"page={page}"
    return urlunsplit((p.scheme, p.netloc, p.path, query, ""))


def has_next_page(soup: BeautifulSoup, current: int) -> bool:
    nxt = soup.select_one("li.pager__item--next a, li.pager-next a, a[rel=next]")
    if nxt is not None:
        return True
    return soup.find("a", href=re.compile(rf"[?&]page={current + 1}(?:&|$)")) is not None


class OdishaDrupalViewsAdapter(SourceAdapter):
    name = "odisha_drupal_views"

    def iter_listing_pages(self, state: dict[str, Any], mode: str) -> Iterator[ListingPage]:
        page = int(state.get("page", 0))
        while True:
            url = page_url(self.source.base_url, page)
            resp = self.client.get_text(url)
            soup = BeautifulSoup(resp.text, "lxml")
            last = not has_next_page(soup, page)
            yield ListingPage(url=url, html=resp.text, page_index=page, next_state={"page": page + 1}, is_last=last)
            if last:
                return
            page += 1

    def extract_listing_metadata(self, listing: ListingPage) -> list[dict[str, Any]]:
        soup = BeautifulSoup(listing.html, "lxml")
        table = soup.select_one("table.views-table")
        if table is None:
            return []
        rows = []
        for tr in table.select("tbody tr") or table.find_all("tr")[1:]:
            row: dict[str, Any] = {}
            for td in tr.find_all("td"):
                classes = td.get("class") or []
                for cls in classes:
                    if cls in FIELD_MAP:
                        row[FIELD_MAP[cls]] = clean_text(td.get_text(" "))
            pdf_links = [a["href"] for a in tr.find_all("a", href=True) if ".pdf" in a["href"].lower()]
            links = pdf_links or [a["href"] for a in tr.find_all("a", href=True)]
            if not links or not row.get("title"):
                continue
            row["href"] = links[0]
            row["extra_links"] = links[1:]
            size = re.search(r"\(([\d.]+\s*[KMG]B)\)", tr.get_text(" "))
            row["size"] = size.group(1) if size else None
            rows.append(row)
        return rows

    def resolve_document_url(self, row: dict[str, Any], listing: ListingPage) -> str:
        return canonicalize_url(urljoin(listing.url, row["href"]))

    def normalize_metadata(self, row: dict[str, Any], document_url: str, listing: ListingPage) -> DiscoveredDocument:
        default_type = self.options.get("default_document_type", "other")
        path = urlsplit(document_url).path
        # The file path is the only stable identifier these portals expose.
        canonical_id = path if len(path) <= 240 else "sha1:" + hashlib.sha1(path.encode()).hexdigest()
        return DiscoveredDocument(
            source_key=self.source.key,
            canonical_id=canonical_id,
            state="odisha",
            department=row.get("department") or self.source.department,
            document_type=classify_document_type(row["title"], default=default_type),
            document_number=row.get("letter_number") or None,
            title=row["title"],
            publication_date=parse_date(row.get("date")),
            language=detect_language(row["title"], "odisha"),
            document_url=document_url,
            listing_url=listing.url,
            raw={**row, "listing_page": listing.page_index},
        )
