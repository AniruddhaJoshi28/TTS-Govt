"""Opt-in, low-volume checks against the real portals.

Run with:  GR_LIVE_TESTS=1 pytest -m live tests/live
Each test fetches at most one listing page and one PDF, at the configured polite rate.
"""

from __future__ import annotations

import os

import pytest

from core.config.sources import get_source
from core.validation import validate_pdf_file
from crawlers.base.http import PoliteClient
from crawlers.base.registry import build_adapter

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("GR_LIVE_TESTS") != "1", reason="set GR_LIVE_TESTS=1 to hit real sites"),
]


@pytest.fixture(autouse=True)
def polite(monkeypatch):
    monkeypatch.setenv("GR_MIN_REQUEST_INTERVAL_S", "2")
    monkeypatch.setenv("GR_OBEY_ROBOTS_TXT", "true")
    from core.config.settings import get_settings

    get_settings.cache_clear()


@pytest.mark.parametrize("key", ["mh_gr_portal", "od_stsc_resolutions", "od_agri_resolutions", "mp_socialjustice_circulars"])
def test_live_discover_and_download_one(key, tmp_path):
    src = get_source(key)
    adapter = build_adapter(src, PoliteClient(src.allowed_hosts))
    try:
        docs = list(adapter.discover_documents(mode="backfill", max_pages=1))
        assert docs, f"{key}: no documents discovered — selectors may have changed"
        assert all(d.document_url.startswith("https://") for d in docs)
        result = adapter.fetch_document(docs[0], dest_dir=tmp_path)
        assert validate_pdf_file(result.path) >= 1
    finally:
        adapter.client.close()
