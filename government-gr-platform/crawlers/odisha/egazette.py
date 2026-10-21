"""Odisha eGazette (egazette.odisha.gov.in) — CSRF-protected POST search.

Audit findings (2026-10-21):
* GET /search_gazette/ returns a form posting to /search_gazette_result with hidden
  ``csrf_gazette_odisha`` and fields gType (1=Extraordinary, 2=Weekly), cYear, monthName,
  weekTime, deptID, notNum, sByFdate, sByTdate, keywords. No CAPTCHA observed.
* The year selector only offered 2024; searches for 2024/Jan and 2026 returned
  "In this section no document available at this moment". No document row could be observed,
  so the result-row parser below targets the generic 5-column result table
  (SL.No / Department / Subject / Date / Download) and is marked PARTIALLY_WORKING until a
  real result row is captured.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.schemas import DiscoveredDocument
from core.validation import canonicalize_url
from crawlers.base.adapter import ListingPage, SourceAdapter
from services.metadata import clean_text, detect_language, parse_date

SEARCH_URL = "https://egazette.odisha.gov.in/search_gazette/"


class OdishaEGazetteAdapter(SourceAdapter):
    name = "odisha_egazette"

    def initial_state(self, mode: str) -> dict[str, Any]:
        return {"queue": None, "index": 0}

    def _search_plan(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        form = soup.find("form", action=lambda a: a and "search_gazette_result" in a)
        years = [o.get("value") for o in form.find("select", attrs={"name": "cYear"}).find_all("option") if o.get("value")]
        return [{"cYear": y, "gType": g, "monthName": f"{m:02d}"} for y in years for g in ("1", "2") for m in range(1, 13)]

    def iter_listing_pages(self, state: dict[str, Any], mode: str) -> Iterator[ListingPage]:
        resp = self.client.get_text(SEARCH_URL)
        soup = BeautifulSoup(resp.text, "lxml")
        plan = state.get("queue") or self._search_plan(soup)
        idx = int(state.get("index", 0))
        while idx < len(plan):
            form = soup.find("form", action=lambda a: a and "search_gazette_result" in a)
            data = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
            data.update({s["name"]: "" for s in form.find_all("select") if s.get("name")})
            data.update(plan[idx])
            result = self.client.post_form(form["action"], data, headers={"Referer": SEARCH_URL})
            yield ListingPage(url=form["action"], html=result.text, page_index=idx,
                              next_state={"queue": plan, "index": idx + 1}, is_last=idx + 1 >= len(plan),
                              extra={"query": plan[idx]})
            # CSRF tokens rotate: refresh the form before the next search.
            soup = BeautifulSoup(self.client.get_text(SEARCH_URL).text, "lxml")
            idx += 1

    def extract_listing_metadata(self, listing: ListingPage) -> list[dict[str, Any]]:
        soup = BeautifulSoup(listing.html, "lxml")
        rows = []
        for table in soup.find_all("table"):
            header = [clean_text(th.get_text()).lower() for th in table.find_all("th")]
            if "subject" not in header:
                continue
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                link = tr.find("a", href=True)
                if len(tds) < 4 or link is None:
                    continue
                cells = [clean_text(td.get_text(" ")) for td in tds]
                rows.append({"department": cells[1], "subject": cells[2], "date": cells[3], "href": link["href"],
                             "query": listing.extra.get("query")})
        return rows

    def resolve_document_url(self, row: dict[str, Any], listing: ListingPage) -> str:
        return canonicalize_url(urljoin(listing.url, row["href"]))

    def normalize_metadata(self, row: dict[str, Any], document_url: str, listing: ListingPage) -> DiscoveredDocument:
        return DiscoveredDocument(
            source_key=self.source.key,
            canonical_id=document_url,
            state="odisha",
            department=row["department"] or None,
            document_type="gazette",
            title=row["subject"],
            publication_date=parse_date(row["date"]),
            language=detect_language(row["subject"], "odisha"),
            document_url=document_url,
            listing_url=SEARCH_URL,
            raw=row,
        )
