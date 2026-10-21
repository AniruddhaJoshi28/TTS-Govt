"""Structured JSON logging and Prometheus metrics."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from prometheus_client import Counter, Gauge, Histogram


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "ctx", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)


def log(logger: logging.Logger, level: int, msg: str, **ctx: Any) -> None:
    logger.log(level, msg, extra={"ctx": ctx})


HTTP_REQUESTS = Counter("gr_http_requests_total", "Outbound HTTP requests", ["host", "status"])
HTTP_RETRIES = Counter("gr_http_retries_total", "Outbound HTTP retries", ["host", "reason"])
DOCS_DISCOVERED = Counter("gr_documents_discovered_total", "Documents seen on listings", ["source"])
DOCS_DOWNLOADED = Counter("gr_documents_downloaded_total", "Validated PDFs stored", ["source"])
DOCS_FAILED = Counter("gr_documents_failed_total", "Document processing failures", ["source", "stage"])
DOWNLOAD_BYTES = Counter("gr_download_bytes_total", "Bytes downloaded", ["source"])
EXTRACTION_SECONDS = Histogram("gr_extraction_seconds", "Text extraction duration per document")
CRAWL_RUNS = Counter("gr_crawl_runs_total", "Crawl runs", ["source", "mode", "status"])
LAST_CRAWL_SUCCESS = Gauge("gr_last_crawl_success_timestamp", "Unix time of last successful crawl", ["source"])
