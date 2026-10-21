"""Scrapy runtime for the source adapters.

The adapters' parsing methods (``extract_listing_metadata`` / ``resolve_document_url`` /
``normalize_metadata``) are pure functions of HTML, so Scrapy drives fetching + pagination here and
reuses them unchanged. This gives AutoThrottle, Scrapy's robots.txt middleware, HTTP cache and
concurrency control for large backfills; the HTTPX ``PoliteClient`` path (``grctl crawl``) remains the
default for scheduled incremental runs because it supports checkpoints and conditional GETs directly.

Run:  scrapy runspider apps/crawler/scrapy_spider.py -a source=od_stsc_resolutions -a max_pages=2
Set GR_SCRAPY_PLAYWRIGHT=1 to route requests flagged ``meta={"playwright": True}`` through
scrapy-playwright (no audited source currently needs a browser).
"""

from __future__ import annotations

import os
from typing import Any

import scrapy
from scrapy.http import FormRequest, Response

from core.config.settings import get_settings
from core.config.sources import get_source
from crawlers.base.adapter import ListingPage
from crawlers.base.registry import build_adapter
from crawlers.madhya_pradesh.socialjustice import max_offset
from crawlers.maharashtra.gr_portal import aspnet_form_fields, parse_total_pages
from crawlers.odisha.drupal_views import has_next_page, page_url


def scrapy_settings() -> dict[str, Any]:
    s = get_settings()
    settings: dict[str, Any] = {
        "USER_AGENT": s.user_agent,
        "ROBOTSTXT_OBEY": s.obey_robots_txt,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": s.min_request_interval_s,
        "DOWNLOAD_DELAY_JITTER": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": max(1.0, s.min_request_interval_s),
        "AUTOTHROTTLE_MAX_DELAY": 60.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 0.5,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": s.max_retries,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504, 522, 524],
        "DOWNLOAD_TIMEOUT": s.request_timeout_s,
        "DOWNLOAD_MAXSIZE": s.max_pdf_bytes,
        "REDIRECT_MAX_TIMES": 5,
        "ITEM_PIPELINES": {"apps.crawler.scrapy_spider.PersistPipeline": 300},
        "LOG_LEVEL": "INFO",
        "TELNETCONSOLE_ENABLED": False,
    }
    if os.environ.get("GR_SCRAPY_PLAYWRIGHT") == "1":
        settings["DOWNLOAD_HANDLERS"] = {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        }
        settings["TWISTED_REACTOR"] = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
    return settings


class AdapterSpider(scrapy.Spider):
    name = "gr_adapter"
    custom_settings = scrapy_settings()

    def __init__(self, source: str, max_pages: str | int = 5, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfg = get_source(source)
        self.adapter = build_adapter(self.cfg)
        self.allowed_domains = list(self.cfg.allowed_hosts)  # OffsiteMiddleware enforces the allowlist
        self.max_pages = int(max_pages)

    async def start(self):
        if self.adapter.name == "mp_socialjustice_ajax":
            yield scrapy.Request("https://socialjustice.mp.gov.in/circular", callback=self.mp_start)
        else:
            yield scrapy.Request(self.cfg.base_url, cb_kwargs={"page": 0 if self.adapter.name == "odisha_drupal_views" else 1})

    # -- shared row handling -------------------------------------------------------------
    def emit(self, response: Response, page: int, url: str | None = None, **extra):
        listing = ListingPage(url=url or response.url, html=response.text, page_index=page, next_state={}, extra=extra)
        for row in self.adapter.extract_listing_metadata(listing):
            try:
                doc = self.adapter.normalize_metadata(row, self.adapter.resolve_document_url(row, listing), listing)
            except Exception as exc:
                self.logger.warning("row skipped: %s", exc)
                continue
            yield doc.model_dump(mode="json")

    # -- per-portal pagination -------------------------------------------------------------
    def parse(self, response: Response, page: int):
        yield from self.emit(response, page)
        if page + 1 >= self.max_pages + (1 if self.adapter.name == "maharashtra_gr_portal" else 0):
            return
        if self.adapter.name == "odisha_drupal_views":
            if has_next_page(_soup(response), page):
                yield response.follow(page_url(self.cfg.base_url, page + 1), cb_kwargs={"page": page + 1})
        elif self.adapter.name == "maharashtra_gr_portal":
            soup = _soup(response)
            total = parse_total_pages(soup) or 1
            if page < total:
                form = aspnet_form_fields(soup)
                form["ctl00$SitePH$ucPaging$txtPageNo"] = str(page + 1)
                form["ctl00$SitePH$ucPaging$btnGo"] = "Go"
                yield FormRequest(self.cfg.base_url, formdata=form, cb_kwargs={"page": page + 1}, dont_filter=True)

    def mp_start(self, response: Response):
        yield self._mp_page(0)

    def _mp_page(self, offset: int) -> FormRequest:
        return FormRequest(
            f"https://socialjustice.mp.gov.in/Circular/ajaxPaginationData/{offset}",
            formdata={"page": str(offset), "cat_id": "", "issed_by": "", "year": "", "sTitle": "", "csrf_token_id": ""},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://socialjustice.mp.gov.in/circular"},
            callback=self.mp_parse, cb_kwargs={"offset": offset},
        )

    def mp_parse(self, response: Response, offset: int):
        page = offset // 10
        yield from self.emit(response, page, listing_url="https://socialjustice.mp.gov.in/circular")
        if offset < max_offset(_soup(response)) and page + 1 < self.max_pages:
            yield self._mp_page(offset + 10)


def _soup(response: Response):
    from bs4 import BeautifulSoup

    return BeautifulSoup(response.text, "lxml")


class PersistPipeline:
    """Upserts each discovered document and queues its download (same code path as grctl)."""

    def open_spider(self) -> None:
        from core.database.session import create_all, session_scope
        from services.discovery.pipeline import sync_sources

        if get_settings().database_url.startswith("sqlite"):
            create_all()
        with session_scope() as s:
            sync_sources(s)

    def process_item(self, item: dict) -> dict:
        from core.database.session import session_scope
        from core.schemas import DiscoveredDocument
        from services.discovery.pipeline import download_document, upsert_discovered
        from services.discovery.queue import enqueue

        doc = DiscoveredDocument(**item)
        with session_scope() as s:
            row, _, changed = upsert_discovered(s, doc, None)
            doc_id, needs = row.id, row.download_status in ("pending", "failed") or changed
        if needs and os.environ.get("GR_SCRAPY_DOWNLOAD", "1") == "1":
            enqueue(download_document, doc_id)
        return item
