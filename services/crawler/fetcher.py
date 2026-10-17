"""Polite, bounded HTTP fetcher (Workstream A, task 2).

Refuses sources that are not cleared for crawling, stays on the source's own
host (including after redirects), rate-limits per host, retries transient
failures a bounded number of times and detects truncated downloads.
"""

import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

from services.source_registry.registry import Source

USER_AGENT = "GovGRAssistant/0.1 (+contact: project team)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 120.0


class SourceNotCrawlable(PermissionError):
    pass


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None = None
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    retryable: bool = False


class Fetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: float = 30.0,
        max_attempts: int = 3,
        backoff: float = 2.0,
        min_interval: float = 2.0,
        max_bytes: int = 50 * 1024 * 1024,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()

    def fetch(self, source: Source, url: str) -> FetchResult:
        if not source.crawlable:
            raise SourceNotCrawlable(f"source {source.id!r} is not verified and cleared for crawling")
        allowed_host = urlsplit(str(source.base_url)).hostname
        host = urlsplit(url).hostname
        if host != allowed_host:
            return FetchResult(url, ok=False, error=f"off-source host {host!r}")

        error = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            self._throttle(host)
            delay = self.backoff**attempt
            try:
                resp = self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True)
            except (requests.Timeout, requests.ConnectionError) as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                try:
                    result = self._read(source, url, allowed_host, resp)
                finally:
                    resp.close()
                if result.ok or not result.retryable:
                    return result
                error = result.error
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), MAX_RETRY_AFTER)
            if attempt < self.max_attempts:
                self._sleep(delay)
        return FetchResult(url, ok=False, error=error, retryable=True)

    def _read(self, source: Source, url: str, allowed_host: str, resp) -> FetchResult:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        final_host = urlsplit(resp.url).hostname
        if final_host != allowed_host:
            return FetchResult(url, ok=False, status=resp.status_code, error=f"redirected off-source to {final_host!r}")
        if resp.status_code in RETRYABLE_STATUS:
            return FetchResult(url, ok=False, status=resp.status_code, error=f"HTTP {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            return FetchResult(url, ok=False, status=resp.status_code, error=f"HTTP {resp.status_code}")

        chunks, size = [], 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > self.max_bytes:
                return FetchResult(url, ok=False, status=resp.status_code, error="exceeds size limit")
            chunks.append(chunk)
        content = b"".join(chunks)

        expected = headers.get("content-length", "")
        if expected.isdigit() and int(expected) != len(content):
            return FetchResult(
                url, ok=False, status=resp.status_code, retryable=True,
                error=f"partial download: {len(content)} of {expected} bytes",
            )
        if not content:
            return FetchResult(url, ok=False, status=resp.status_code, error="empty response", retryable=True)
        return FetchResult(url, ok=True, status=resp.status_code, content=content, headers=headers)
