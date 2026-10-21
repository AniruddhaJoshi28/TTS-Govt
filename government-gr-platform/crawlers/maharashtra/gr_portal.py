"""Maharashtra GR portal (gr.maharashtra.gov.in) — ASP.NET WebForms.

Audit findings (2026-10-21):
* Listing table ``#SitePH_dgvDocuments``: Sr / Department / Title / Unique code (सांकेतांक) / GR date / KB / PDF link.
* Default view lists recent GRs (≈ last 7 days, ~25 pages x 10 rows). Pagination is a postback
  with ``ctl00$SitePH$ucPaging$txtPageNo`` + ``btnGo`` and does NOT require the CAPTCHA.
* Date-range / department search requires the image CAPTCHA (``txtimgcode``) → not automated.
  Historical backfill uses the Orgpedia seed list instead (see orgpedia_seed.py).
* PDFs: ``/Site/Upload/Government%20Resolutions/{Marathi|English}/<code>.pdf``; both language folders
  serve identical bytes, so the canonical URL always uses ``Marathi``. HEAD returns 404; GET works,
  with ETag + Last-Modified (conditional GET supported).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.schemas import DiscoveredDocument
from crawlers.base.adapter import ListingPage, SourceAdapter
from services.metadata import clean_text, normalize_department, parse_date, to_ascii_digits

PDF_BASE = "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/Marathi/"
CODE_RE = re.compile(r"^\d{18}$")


def canonical_pdf_url(code: str) -> str:
    return f"{PDF_BASE}{code}.pdf"


def aspnet_form_fields(soup: BeautifulSoup) -> dict[str, str]:
    """Collect the hidden/text/select/radio state an ASP.NET postback needs."""
    data: dict[str, str] = {}
    form = soup.find("form") or soup
    for inp in form.find_all("input"):
        name, typ = inp.get("name"), (inp.get("type") or "text").lower()
        if not name:
            continue
        if typ in ("hidden", "text"):
            data[name] = inp.get("value", "")
        elif typ == "radio" and inp.has_attr("checked"):
            data[name] = inp.get("value", "")
    for sel in form.find_all("select"):
        opt = sel.find("option", selected=True) or sel.find("option")
        if sel.get("name"):
            data[sel["name"]] = opt.get("value", "") if opt else ""
    return data


def parse_total_pages(soup: BeautifulSoup) -> int | None:
    el = soup.find(id="SitePH_ucPaging_lblTotalPages")
    if not el:
        return None
    digits = to_ascii_digits(el.get_text(strip=True))
    return int(digits) if digits.isdigit() else None


class MaharashtraGRPortalAdapter(SourceAdapter):
    name = "maharashtra_gr_portal"

    def initial_state(self, mode: str) -> dict[str, Any]:
        return {"page": 1}

    def iter_listing_pages(self, state: dict[str, Any], mode: str) -> Iterator[ListingPage]:
        url = self.source.base_url
        resp = self.client.get_text(url)
        soup = BeautifulSoup(resp.text, "lxml")
        total = parse_total_pages(soup) or 1
        page = max(1, int(state.get("page", 1)))
        html = resp.text
        while page <= total:
            if page > 1:
                form = aspnet_form_fields(soup)
                form["ctl00$SitePH$ucPaging$txtPageNo"] = str(page)
                form["ctl00$SitePH$ucPaging$btnGo"] = "Go"
                resp = self.client.post_form(url, form, headers={"Referer": url})
                html = resp.text
                soup = BeautifulSoup(html, "lxml")
                total = parse_total_pages(soup) or total
            yield ListingPage(url=url, html=html, page_index=page, next_state={"page": page + 1, "total_pages": total},
                              is_last=page >= total, extra={"total_pages": total})
            page += 1

    def extract_listing_metadata(self, listing: ListingPage) -> list[dict[str, Any]]:
        soup = BeautifulSoup(listing.html, "lxml")
        table = soup.find(id="SitePH_dgvDocuments")
        if table is None:
            return []
        rows = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue  # header row uses <th> or fewer cells
            link = tr.find("a", href=True)
            rows.append({
                "serial": clean_text(tds[0].get_text()),
                "department": clean_text(tds[1].get_text()),
                "title": clean_text(tds[2].get_text()),
                "unique_code": to_ascii_digits(clean_text(tds[3].get_text())),
                "gr_date": clean_text(tds[4].get_text()),
                "size_kb": clean_text(tds[5].get_text()),
                "href": link["href"] if link else None,
            })
        return rows

    def resolve_document_url(self, row: dict[str, Any], listing: ListingPage) -> str:
        code = row.get("unique_code", "")
        if CODE_RE.match(code):
            return canonical_pdf_url(code)
        if row.get("href"):
            return urljoin(listing.url, row["href"])
        raise ValueError("row has neither unique code nor link")

    def normalize_metadata(self, row: dict[str, Any], document_url: str, listing: ListingPage) -> DiscoveredDocument:
        code = row["unique_code"]
        return DiscoveredDocument(
            source_key=self.source.key,
            canonical_id=code if CODE_RE.match(code) else document_url,
            state="maharashtra",
            department=normalize_department(row["department"]),
            document_type="government_resolution",
            document_number=code or None,
            title=row["title"],
            publication_date=parse_date(row["gr_date"]),
            language="mr",
            document_url=document_url,
            listing_url=listing.url,
            raw={**row, "listing_page": listing.page_index, "original_href": urljoin(listing.url, row["href"]) if row.get("href") else None},
        )
