"""Listing parsers against HTML captured from the real portals on 2026-10-21."""

from __future__ import annotations

import datetime as dt
import json

from bs4 import BeautifulSoup

from core.config.sources import get_source
from crawlers.base.adapter import ListingPage
from crawlers.base.registry import build_adapter
from crawlers.madhya_pradesh.socialjustice import max_offset
from crawlers.maharashtra.gr_portal import aspnet_form_fields, canonical_pdf_url, parse_total_pages
from crawlers.odisha.drupal_views import has_next_page, page_url
from tests.conftest import FIXTURES, fixture_html


def _listing(html: str, url: str, idx: int = 0, **extra) -> ListingPage:
    return ListingPage(url=url, html=html, page_index=idx, next_state={}, extra=extra)


def test_maharashtra_static_table_parsing():
    adapter = build_adapter(get_source("mh_gr_portal"))
    html = fixture_html("mh_gr_listing_page1.html")
    lp = _listing(html, "https://gr.maharashtra.gov.in/1145/Government-Resolutions", 1)
    rows = adapter.extract_listing_metadata(lp)
    assert len(rows) == 10
    first = rows[0]
    assert first["unique_code"] == "202610211122214422"
    assert first["gr_date"] == "21-10-2026"
    doc = adapter.normalize_metadata(first, adapter.resolve_document_url(first, lp), lp)
    assert doc.canonical_id == "202610211122214422"
    assert doc.document_url == canonical_pdf_url("202610211122214422")
    assert doc.publication_date == dt.date(2026, 10, 21)
    assert doc.department == "सामाजिक न्‍याय व विशेष सहाय्य विभाग"  # ZWJ preserved
    assert doc.title.startswith("सहआयुक्त")
    assert doc.raw["original_href"].endswith("/Site/Upload/Government%20Resolutions/Marathi/202610211122214422.pdf")


def test_maharashtra_pagination_controls():
    soup = BeautifulSoup(fixture_html("mh_gr_listing_page1.html"), "lxml")
    assert parse_total_pages(soup) == 25  # rendered as Devanagari "२५"
    form = aspnet_form_fields(soup)
    assert "__VIEWSTATE" in form and "__EVENTVALIDATION" in form
    assert form["ctl00$SitePH$rblDateFilter"] == "1"
    assert form["ctl00$SitePH$txtimgcode"] == ""  # CAPTCHA field is never filled


def test_odisha_drupal_views_parsing_by_field_class():
    for key, fixture, expected_rows in [("od_stsc_resolutions", "od_stsc_resolutions.html", 20),
                                        ("od_agri_resolutions", "od_agri_resolutions.html", 17)]:
        src = get_source(key)
        adapter = build_adapter(src)
        lp = _listing(fixture_html(fixture), src.base_url)
        rows = adapter.extract_listing_metadata(lp)
        assert len(rows) == expected_rows, key
        doc = adapter.normalize_metadata(rows[0], adapter.resolve_document_url(rows[0], lp), lp)
        assert doc.state == "odisha"
        assert doc.document_url.startswith(f"https://{src.allowed_hosts[0]}/sites/default/files/")
        assert doc.canonical_id.startswith("/sites/default/files/")
        assert doc.publication_date is not None
        assert doc.document_number


def test_odisha_column_order_differs_but_fields_match():
    src = get_source("od_agri_resolutions")
    adapter = build_adapter(src)
    rows = adapter.extract_listing_metadata(_listing(fixture_html("od_agri_resolutions.html"), src.base_url))
    assert rows[0]["date"] == "29/08/2026" and rows[0]["letter_number"] == "1356"


def test_odisha_pagination():
    soup = BeautifulSoup(fixture_html("od_stsc_resolutions.html"), "lxml")
    assert has_next_page(soup, 0)
    assert page_url("https://x.gov.in/en/list", 0) == "https://x.gov.in/en/list"
    assert page_url("https://x.gov.in/en/list?page=3", 5) == "https://x.gov.in/en/list?page=5"


def test_mp_dynamic_ajax_listing_parsing():
    src = get_source("mp_socialjustice_circulars")
    adapter = build_adapter(src)
    html = fixture_html("mp_socialjustice_ajax0.html")
    lp = _listing(html, "https://socialjustice.mp.gov.in/Circular/ajaxPaginationData/0", listing_url="https://socialjustice.mp.gov.in/circular")
    rows = adapter.extract_listing_metadata(lp)
    assert len(rows) == 10
    doc = adapter.normalize_metadata(rows[0], adapter.resolve_document_url(rows[0], lp), lp)
    assert doc.document_number == "एफ 8-2/2013/आ.प्र./एक (पार्ट)"
    assert doc.publication_date == dt.date(2026, 10, 9)
    assert doc.language == "hi"
    assert "%E0%A4" in doc.document_url  # Devanagari file name percent-encoded consistently
    assert max_offset(BeautifulSoup(html, "lxml")) >= 20


def test_mp_www_host_normalised():
    adapter = build_adapter(get_source("mp_socialjustice_circulars"))
    lp = _listing("", "https://socialjustice.mp.gov.in/x")
    url = adapter.resolve_document_url({"href": "https://www.socialjustice.mp.gov.in/uploads/files/a.pdf"}, lp)
    assert url == "https://socialjustice.mp.gov.in/uploads/files/a.pdf"


def test_egazette_empty_result_page():
    adapter = build_adapter(get_source("od_egazette"))
    lp = _listing(fixture_html("od_egazette_empty_result.html"), "https://egazette.odisha.gov.in/search_gazette_result")
    assert adapter.extract_listing_metadata(lp) == []


def test_orgpedia_seed_uses_official_url_only():
    src = get_source("mh_orgpedia_backfill")
    adapter = build_adapter(src)
    raw = (FIXTURES / "json" / "orgpedia_mahagri_sample.json").read_text(encoding="utf-8")
    lp = _listing(raw, "https://raw.githubusercontent.com/orgpedia/mahagri/main/import/documents/documents.json", repo="mahagri")
    rows = adapter.extract_listing_metadata(lp)
    assert len(rows) == len(json.loads(raw))
    doc = adapter.normalize_metadata(rows[0], adapter.resolve_document_url(rows[0], lp), lp)
    assert doc.source_key == "mh_gr_portal"
    assert doc.document_url.startswith("https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/Marathi/")
    assert doc.raw["provenance"]["seed"] == "orgpedia"


def test_odisha_columns_mapped_by_header_when_field_names_are_misleading():
    # agri.odisha.gov.in notifications keep the date in "field-date-of-birth" and the number
    # in "field-number-of-tweet"; the header labels ("Date", "Notification No.") are authoritative.
    src = get_source("od_agri_notifications")
    adapter = build_adapter(src)
    lp = _listing(fixture_html("od_agri_notifications.html"), src.base_url)
    rows = adapter.extract_listing_metadata(lp)
    assert rows[0]["date"] == "10/05/2021"  # most date cells on this portal are genuinely empty
    assert sum(1 for r in rows if r.get("letter_number")) >= len(rows) // 2  # "Notification No." column
    doc = adapter.normalize_metadata(rows[0], adapter.resolve_document_url(rows[0], lp), lp)
    assert doc.publication_date is not None
