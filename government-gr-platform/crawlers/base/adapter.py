"""Common source-adapter interface.

Each state/portal gets its own adapter subclass; they share only this control loop, not selectors.

Control flow of :meth:`SourceAdapter.discover_documents`::

    state = checkpoint or initial_state()
    for listing in iter_listing_pages(state):          # adapter-specific fetching / pagination
        rows = extract_listing_metadata(listing)       # adapter-specific parsing (pure function)
        for row in rows:
            url = resolve_document_url(row, listing)   # absolute, allowlisted PDF URL
            doc = normalize_metadata(row, url, listing)# -> DiscoveredDocument
            yield doc
        persist_discovery_state(listing.next_state)    # checkpoint after every listing page
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config.sources import SourceConfig
from core.observability import log
from core.schemas import DiscoveredDocument
from core.validation import check_url_allowed
from crawlers.base.http import DownloadResult, PoliteClient

logger = logging.getLogger(__name__)


@dataclass
class ListingPage:
    url: str
    html: str
    page_index: int
    next_state: dict[str, Any]
    is_last: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


CheckpointSaver = Callable[[dict[str, Any], bool], None]
KnownChecker = Callable[[str], bool]


class SourceAdapter(abc.ABC):
    #: registry name referenced by ``adapter:`` in sources.yaml
    name: str = ""
    #: True if the listing requires a real browser (Playwright). All audited sources work over HTTP.
    requires_browser: bool = False

    def __init__(self, source: SourceConfig, client: PoliteClient | None = None):
        self.source = source
        self.options = source.options
        self.client = client or PoliteClient(source.allowed_hosts)

    # ---- adapter-specific hooks ------------------------------------------------------
    def initial_state(self, mode: str) -> dict[str, Any]:
        return {"page": 0}

    @abc.abstractmethod
    def iter_listing_pages(self, state: dict[str, Any], mode: str) -> Iterator[ListingPage]:
        """Fetch listing pages starting from ``state``; yield one ListingPage per page."""

    @abc.abstractmethod
    def extract_listing_metadata(self, listing: ListingPage) -> list[dict[str, Any]]:
        """Parse raw row dicts out of a listing page. Must be a pure function of the HTML."""

    @abc.abstractmethod
    def resolve_document_url(self, row: dict[str, Any], listing: ListingPage) -> str:
        """Return the absolute official PDF URL for a row."""

    @abc.abstractmethod
    def normalize_metadata(self, row: dict[str, Any], document_url: str, listing: ListingPage) -> DiscoveredDocument:
        """Convert a raw row into a validated DiscoveredDocument."""

    # ---- shared behaviour -------------------------------------------------------------
    def fetch_document(self, doc: DiscoveredDocument, *, etag: str | None = None,
                       last_modified: str | None = None, dest_dir: Path | None = None) -> DownloadResult:
        check_url_allowed(doc.document_url, self.source.allowed_hosts)
        return self.client.download_pdf(
            doc.document_url, etag=etag, last_modified=last_modified, referer=doc.listing_url, dest_dir=dest_dir
        )

    def persist_discovery_state(self, saver: CheckpointSaver | None, state: dict[str, Any], completed: bool) -> None:
        if saver:
            saver(state, completed)

    def discover_documents(
        self,
        mode: str = "incremental",
        checkpoint: dict[str, Any] | None = None,
        save_checkpoint: CheckpointSaver | None = None,
        is_known: KnownChecker | None = None,
        max_pages: int | None = None,
        stop_after_known_pages: int = 2,
    ) -> Iterator[DiscoveredDocument]:
        """Yield documents from listings, checkpointing after each page.

        Incremental mode stops after ``stop_after_known_pages`` consecutive pages whose documents
        are all already known; backfill mode walks until the archive is exhausted or ``max_pages``.
        """
        state = dict(checkpoint) if checkpoint else self.initial_state(mode)
        max_pages = max_pages or int(self.options.get("max_pages", 50))
        known_streak = 0
        pages = 0
        self.pages_fetched = 0
        completed = False
        for listing in self.iter_listing_pages(state, mode):
            pages += 1
            self.pages_fetched = pages
            rows = self.extract_listing_metadata(listing)
            page_all_known = bool(rows)
            for row in rows:
                try:
                    url = self.resolve_document_url(row, listing)
                    doc = self.normalize_metadata(row, url, listing)
                except Exception as exc:  # one bad row must not kill the crawl
                    log(logger, logging.WARNING, "row skipped", source=self.source.key, url=listing.url, error=str(exc), row=str(row)[:300])
                    continue
                if is_known is None or not is_known(doc.canonical_id):
                    page_all_known = False
                yield doc
            completed = listing.is_last or not rows
            self.persist_discovery_state(save_checkpoint, listing.next_state, completed)
            if completed:
                break
            if mode == "incremental":
                known_streak = known_streak + 1 if page_all_known else 0
                if known_streak >= stop_after_known_pages:
                    log(logger, logging.INFO, "incremental stop: reached known documents", source=self.source.key, page=listing.page_index)
                    break
            if pages >= max_pages:
                break
        self.completed = completed
