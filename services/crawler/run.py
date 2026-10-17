"""Runs one crawl of a source and records its outcome (Workstream A, tasks 7, 8)."""

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from services.crawler.fetcher import Fetcher
from services.document_ingestion.store import DocumentStore
from services.source_registry.registry import Source


class SiteAdapter(Protocol):
    """Site-specific discovery of document URLs (listing pages, pagination, search)."""

    source_id: str

    def discover(self, fetcher: Fetcher, source: Source) -> Iterable[str]: ...


@dataclass
class CrawlReport:
    run_id: int
    status: str  # "ok" | "partial" | "failed" | "empty"
    counts: dict[str, int]


def crawl(source: Source, urls: Iterable[str], fetcher: Fetcher, store: DocumentStore) -> CrawlReport:
    """Fetch and ingest the given URLs plus any retries that are due."""
    targets = list(dict.fromkeys([*urls, *store.due_retries(source.id)]))
    run_id = store.start_run(source.id)
    counts: Counter[str] = Counter()

    for url in targets:
        result = fetcher.fetch(source, url)
        if not result.ok:
            store.record_failure(source.id, url, result.error or "unknown error", retryable=result.retryable)
            counts["failed"] += 1
            continue
        ingested = store.ingest(
            source.id,
            url,
            result.content,
            http_status=result.status,
            content_type=result.headers.get("content-type"),
            etag=result.headers.get("etag"),
            last_modified=result.headers.get("last-modified"),
        )
        counts[ingested.status] += 1

    if not targets:
        status = "empty"
    elif counts["failed"] == 0:
        status = "ok"
    elif counts["failed"] == len(targets):
        status = "failed"
    else:
        status = "partial"
    store.finish_run(run_id, status, json.dumps(dict(counts)))
    return CrawlReport(run_id, status, dict(counts))
