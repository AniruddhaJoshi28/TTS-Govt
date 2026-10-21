"""Polite, safe HTTP client used by every adapter and by the PDF downloader.

Guarantees:
* only allowlisted public hosts are contacted, including every redirect hop (SSRF guard);
* robots.txt is honoured when the site publishes one (a 4xx robots.txt means "no rules");
* at most one request per ``min_interval`` seconds per host;
* retries with exponential backoff + jitter on network errors, 429 and 5xx, honouring Retry-After;
* 403/401/404 are not retried (no evasion of access controls);
* PDF downloads are streamed to disk with a hard size cap, content-type and signature checks.
"""

from __future__ import annotations

import email.utils
import logging
import random
import tempfile
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from core.config.settings import get_settings
from core.observability import HTTP_REQUESTS, HTTP_RETRIES, log
from core.validation import UnsafeURLError, check_url_allowed, looks_like_pdf

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504, 520, 521, 522, 524}
MAX_REDIRECTS = 5
REDIRECT_STATUS = {301, 302, 303, 307, 308}  # not httpx.is_redirect: that also matches 304


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class AccessDenied(FetchError):
    """401/403 or robots.txt disallow. Never retried or worked around."""


class RobotsDisallowed(AccessDenied):
    pass


class DownloadTooLarge(FetchError):
    pass


class NotAPDF(FetchError):
    pass


@dataclass
class DownloadResult:
    path: Path | None
    status: int
    final_url: str
    content_type: str | None
    etag: str | None
    last_modified: str | None
    size: int
    not_modified: bool = False
    redirects: list[str] = field(default_factory=list)


class HostRateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            ready = self._next.get(host, now)
            delay = max(0.0, ready - now)
            self._next[host] = max(now, ready) + self.min_interval
        if delay:
            time.sleep(delay)

    def penalise(self, host: str, seconds: float) -> None:
        with self._lock:
            self._next[host] = max(self._next.get(host, 0.0), time.monotonic() + seconds)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


class PoliteClient:
    def __init__(
        self,
        allowed_hosts: list[str],
        *,
        user_agent: str | None = None,
        min_interval: float | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        obey_robots: bool | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        s = get_settings()
        self.allowed_hosts = [h.lower() for h in allowed_hosts]
        self.user_agent = user_agent or s.user_agent
        self.max_retries = s.max_retries if max_retries is None else max_retries
        self.backoff_base = s.backoff_base_s
        self.backoff_max = s.backoff_max_s
        self.obey_robots = s.obey_robots_txt if obey_robots is None else obey_robots
        self.max_pdf_bytes = s.max_pdf_bytes
        self.limiter = HostRateLimiter(s.min_request_interval_s if min_interval is None else min_interval)
        self._sleep = sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        # Redirects are followed manually so each hop can be validated against the allowlist.
        self.client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Language": "en,hi;q=0.8,mr;q=0.7,or;q=0.6"},
            timeout=httpx.Timeout(timeout or s.request_timeout_s, connect=20.0),
            follow_redirects=False,
            transport=transport,
        )
        self.request_count = 0

    # -- lifecycle -----------------------------------------------------------------
    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- robots.txt ----------------------------------------------------------------
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            self.limiter.wait(p.netloc)
            resp = self.client.get(origin + "/robots.txt")
            self.request_count += 1
            ctype = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "html" not in ctype.lower():
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
            # 4xx / HTML soft-404: site publishes no robots rules.
        except httpx.HTTPError as exc:
            log(logger, logging.WARNING, "robots.txt fetch failed; proceeding conservatively", url=origin, error=str(exc))
        self._robots[origin] = parser
        return parser

    def check_robots(self, url: str) -> None:
        if not self.obey_robots:
            return
        parser = self._robots_for(url)
        if parser is not None and not parser.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}", status=None)

    # -- core request ----------------------------------------------------------------
    def _backoff(self, attempt: int) -> float:
        base = min(self.backoff_max, self.backoff_base * (2**attempt))
        return base / 2 + random.uniform(0, base / 2)  # "equal jitter"

    def _send_following_redirects(self, method: str, url: str, *, stream: bool, **kwargs) -> tuple[httpx.Response, list[str]]:
        hops: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            check_url_allowed(current, self.allowed_hosts)
            host = urlsplit(current).netloc
            self.limiter.wait(host)
            req = self.client.build_request(method, current, **kwargs)
            resp = self.client.send(req, stream=stream)
            self.request_count += 1
            HTTP_REQUESTS.labels(host=host, status=str(resp.status_code)).inc()
            if resp.status_code in REDIRECT_STATUS:
                location = resp.headers.get("location")
                resp.close()
                if not location:
                    raise FetchError(f"redirect without Location from {current}", resp.status_code)
                current = urljoin(current, location)
                hops.append(current)
                if resp.status_code in (301, 302, 303) and method == "POST":
                    method, kwargs = "GET", {k: v for k, v in kwargs.items() if k in ("headers", "params")}
                continue
            return resp, hops
        raise FetchError(f"too many redirects from {url}")

    def request(self, method: str, url: str, *, stream: bool = False, **kwargs) -> httpx.Response:
        """Perform a request with retry policy. Caller must close streamed responses."""
        self.check_robots(url)
        last_exc: Exception | None = None
        host = urlsplit(url).netloc
        for attempt in range(self.max_retries + 1):
            try:
                resp, hops = self._send_following_redirects(method, url, stream=stream, **kwargs)
            except UnsafeURLError:
                raise
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                HTTP_RETRIES.labels(host=host, reason=type(exc).__name__).inc()
                delay = self._backoff(attempt)
                log(logger, logging.WARNING, "transport error; retrying", url=url, attempt=attempt, delay=round(delay, 1), error=str(exc))
                self._sleep(delay)
                continue
            resp.extensions["redirect_hops"] = hops
            status = resp.status_code
            if status in (401, 403):
                resp.close()
                raise AccessDenied(f"HTTP {status} for {url}", status=status)
            if status in RETRYABLE_STATUS:
                retry_after = parse_retry_after(resp.headers.get("retry-after"))
                resp.close()
                if attempt >= self.max_retries:
                    raise FetchError(f"HTTP {status} for {url} after {attempt + 1} attempts", status=status, retryable=True)
                delay = min(self.backoff_max, retry_after) if retry_after is not None else self._backoff(attempt)
                if status == 429:
                    self.limiter.penalise(host, delay)
                HTTP_RETRIES.labels(host=host, reason=str(status)).inc()
                log(logger, logging.WARNING, "retryable status", url=url, status=status, attempt=attempt, delay=round(delay, 1))
                self._sleep(delay)
                continue
            return resp
        raise FetchError(f"network failure for {url}: {last_exc}", retryable=True)

    def get_text(self, url: str, **kwargs) -> httpx.Response:
        resp = self.request("GET", url, **kwargs)
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code} for {url}", status=resp.status_code)
        return resp

    def post_form(self, url: str, data: dict, **kwargs) -> httpx.Response:
        resp = self.request("POST", url, data=data, **kwargs)
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code} for POST {url}", status=resp.status_code)
        return resp

    # -- PDF download ----------------------------------------------------------------
    def download_pdf(
        self,
        url: str,
        *,
        dest_dir: Path | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        referer: str | None = None,
    ) -> DownloadResult:
        """Stream a PDF to a temp file. Uses conditional GET when validators are known."""
        headers = {"Accept": "application/pdf,*/*;q=0.5"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if referer:
            headers["Referer"] = referer
        resp = self.request("GET", url, stream=True, headers=headers)
        hops = resp.extensions.get("redirect_hops", [])
        final_url = str(resp.request.url)
        try:
            if resp.status_code == 304:
                return DownloadResult(None, 304, final_url, None, etag, last_modified, 0, not_modified=True, redirects=hops)
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} for {url}", status=resp.status_code)
            ctype = resp.headers.get("content-type")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_pdf_bytes:
                raise DownloadTooLarge(f"declared size {declared} exceeds cap for {url}")
            if ctype and "html" in ctype.lower():
                raise NotAPDF(f"server returned {ctype} instead of a PDF for {url}", status=resp.status_code)
            fd, name = tempfile.mkstemp(suffix=".pdf", dir=dest_dir)
            path = Path(name)
            size = 0
            first = b""
            try:
                with open(fd, "wb") as out:
                    for chunk in resp.iter_bytes(64 * 1024):
                        if not first:
                            first = chunk[:1024]
                            if not looks_like_pdf(first):
                                raise NotAPDF(f"response is not a PDF (content-type={ctype}) for {url}")
                        size += len(chunk)
                        if size > self.max_pdf_bytes:
                            raise DownloadTooLarge(f"download exceeded {self.max_pdf_bytes} bytes for {url}")
                        out.write(chunk)
                if declared and declared.isdigit() and int(declared) != size:
                    raise FetchError(f"incomplete download: {size}/{declared} bytes for {url}", retryable=True)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            return DownloadResult(
                path, resp.status_code, final_url, ctype, resp.headers.get("etag"), resp.headers.get("last-modified"), size, redirects=hops
            )
        except httpx.HTTPError as exc:
            raise FetchError(f"download interrupted for {url}: {exc}", retryable=True) from exc
        finally:
            resp.close()
