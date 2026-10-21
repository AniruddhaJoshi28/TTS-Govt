from __future__ import annotations

from scrapy.http import FormRequest, HtmlResponse, Request

from apps.crawler.scrapy_spider import AdapterSpider, scrapy_settings
from tests.conftest import fixture_html


def _resp(url: str, fixture: str) -> HtmlResponse:
    return HtmlResponse(url=url, body=fixture_html(fixture).encode("utf-8"), encoding="utf-8", request=Request(url))


def test_scrapy_settings_are_polite():
    s = scrapy_settings()
    assert s["AUTOTHROTTLE_ENABLED"] and s["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert 429 in s["RETRY_HTTP_CODES"]


def test_spider_odisha_items_and_next_page():
    spider = AdapterSpider(source="od_stsc_resolutions", max_pages=3)
    assert spider.allowed_domains == ["stsc.odisha.gov.in"]
    out = list(spider.parse(_resp(spider.cfg.base_url, "od_stsc_resolutions.html"), page=0))
    items = [o for o in out if isinstance(o, dict)]
    reqs = [o for o in out if isinstance(o, Request)]
    assert len(items) == 20 and items[0]["state"] == "odisha"
    assert reqs and reqs[0].url.endswith("?page=1")


def test_spider_maharashtra_postback_pagination():
    spider = AdapterSpider(source="mh_gr_portal", max_pages=3)
    out = list(spider.parse(_resp(spider.cfg.base_url, "mh_gr_listing_page1.html"), page=1))
    items = [o for o in out if isinstance(o, dict)]
    reqs = [o for o in out if isinstance(o, FormRequest)]
    assert len(items) == 10
    assert reqs and b"txtPageNo=2" in reqs[0].body and b"__VIEWSTATE=" in reqs[0].body
    assert b"txtimgcode=&" in reqs[0].body or reqs[0].body.endswith(b"txtimgcode=")  # CAPTCHA never filled


def test_spider_mp_ajax_offsets():
    spider = AdapterSpider(source="mp_socialjustice_circulars", max_pages=5)
    out = list(spider.mp_parse(_resp("https://socialjustice.mp.gov.in/Circular/ajaxPaginationData/0", "mp_socialjustice_ajax0.html"), offset=0))
    reqs = [o for o in out if isinstance(o, FormRequest)]
    assert len([o for o in out if isinstance(o, dict)]) == 10
    assert reqs[0].url.endswith("/ajaxPaginationData/10")


def test_scheduler_registers_only_active_sources_with_adapters():
    from apps.scheduler.main import build_scheduler

    jobs = {j.id for j in build_scheduler().get_jobs()}
    assert "crawl:mh_gr_portal" in jobs and "crawl:od_stsc_resolutions" in jobs
    assert "crawl:od_cabinet" not in jobs and "crawl:mh_orgpedia_backfill" not in jobs
