"""URL safety (SSRF / allowlist) and PDF validation."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit


class UnsafeURLError(ValueError):
    pass


class InvalidPDFError(ValueError):
    pass


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def check_url_allowed(url: str, allowed_hosts: list[str] | set[str], resolve_dns: bool = False) -> str:
    """Raise ``UnsafeURLError`` unless ``url`` is an https/http URL to an allowlisted public host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme not allowed: {url}")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURLError(f"missing host: {url}")
    if parts.username or parts.password:
        raise UnsafeURLError(f"credentials in URL not allowed: {url}")
    if _is_private_ip(host) or host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURLError(f"private/internal target: {url}")
    if host not in {h.lower() for h in allowed_hosts}:
        raise UnsafeURLError(f"host not in allowlist: {host}")
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise UnsafeURLError(f"DNS failure for {host}: {exc}") from exc
        for info in infos:
            if _is_private_ip(info[4][0]):
                raise UnsafeURLError(f"{host} resolves to private address {info[4][0]}")
    return url


def canonicalize_url(url: str) -> str:
    """Normalise a URL for identity comparison: lowercase host, drop fragment & default port,
    consistent percent-encoding of the path."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if p.port and not ((p.scheme == "https" and p.port == 443) or (p.scheme == "http" and p.port == 80)):
        host = f"{host}:{p.port}"
    path = quote(unquote(p.path), safe="/%:@!$&'()*+,;=-._~")
    return urlunsplit((p.scheme.lower(), host, path or "/", p.query, ""))


PDF_MAGIC = b"%PDF-"


def looks_like_pdf(head: bytes) -> bool:
    # The PDF spec allows up to 1024 bytes of junk before the header.
    return PDF_MAGIC in head[:1024]


def validate_pdf_file(path: Path, min_bytes: int = 200) -> int:
    """Validate a downloaded file is a parseable PDF. Returns page count."""
    size = path.stat().st_size
    if size < min_bytes:
        raise InvalidPDFError(f"file too small ({size} bytes)")
    with open(path, "rb") as fh:
        head = fh.read(1024)
        fh.seek(max(0, size - 2048))
        tail = fh.read()
    if not looks_like_pdf(head):
        raise InvalidPDFError("missing %PDF- signature")
    if b"%%EOF" not in tail:
        raise InvalidPDFError("missing %%EOF marker (truncated download?)")
    try:
        import pymupdf as fitz

        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise InvalidPDFError("encrypted PDF requires password")
            pages = doc.page_count
    except InvalidPDFError:
        raise
    except Exception as exc:  # malformed structure
        raise InvalidPDFError(f"unparseable PDF: {exc}") from exc
    if pages < 1:
        raise InvalidPDFError("PDF has no pages")
    return pages


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
