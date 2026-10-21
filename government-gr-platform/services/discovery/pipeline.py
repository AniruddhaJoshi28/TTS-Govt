"""Crawl → persist → download → store → extract pipeline.

Every step is idempotent and keyed by database identity, so jobs can be retried or replayed:
* discovery upserts by (source_id, canonical_id);
* downloads are content-addressed (SHA-256) and write-once in object storage;
* extraction replaces a document's page rows atomically.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.config.sources import SourceConfig, load_sources
from core.database.session import session_scope
from core.models import CrawlCheckpoint, CrawlRun, DeadLetter, Document, DocumentPage, DocumentVersion, Source, utcnow
from core.observability import (
    CRAWL_RUNS,
    DOCS_DISCOVERED,
    DOCS_DOWNLOADED,
    DOCS_FAILED,
    DOWNLOAD_BYTES,
    EXTRACTION_SECONDS,
    LAST_CRAWL_SUCCESS,
    log,
)
from core.schemas import DiscoveredDocument
from core.storage import LocalObjectStore, derived_key, get_store, original_key
from core.validation import InvalidPDFError, canonicalize_url, sha256_file, validate_pdf_file
from crawlers.base.http import AccessDenied, DownloadTooLarge, FetchError, NotAPDF, PoliteClient
from crawlers.base.registry import build_adapter
from services.deduplication import find_binary_duplicate, link_duplicate
from services.discovery.queue import enqueue

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_ATTEMPTS = 3
METADATA_FIELDS = ("department", "document_type", "document_number", "title", "publication_date", "language", "original_url")

# Injection point for tests / alternative transports.
ClientFactory = Callable[[list[str]], PoliteClient]
_client_factory: ClientFactory = lambda hosts: PoliteClient(hosts)  # noqa: E731


def set_client_factory(factory: ClientFactory | None) -> None:
    global _client_factory
    _client_factory = factory or (lambda hosts: PoliteClient(hosts))


# --------------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------------

def sync_sources(session: Session, sources: list[SourceConfig] | None = None) -> None:
    for cfg in sources or load_sources():
        row = session.get(Source, cfg.key)
        if row is None:
            row = Source(id=cfg.key)
            session.add(row)
        row.state, row.department, row.name, row.base_url = cfg.state, cfg.department, cfg.name, cfg.base_url
        row.source_type, row.crawl_strategy, row.access_policy = cfg.source_type, cfg.crawl_strategy, cfg.access_policy
        row.audit_status, row.active = cfg.status, cfg.active


def _source_cfg(key: str) -> SourceConfig:
    for s in load_sources():
        if s.key == key:
            return s
    raise KeyError(f"unknown source {key}")


def _hosts_for_document(doc: Document) -> list[str]:
    hosts = set(_source_cfg(doc.source_id).allowed_hosts)
    return sorted(hosts)


# --------------------------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------------------------

def _snapshot(doc: Document) -> dict[str, Any]:
    return {f: (getattr(doc, f).isoformat() if isinstance(getattr(doc, f), dt.date) else getattr(doc, f)) for f in METADATA_FIELDS}


def upsert_discovered(session: Session, item: DiscoveredDocument, run_id: str | None) -> tuple[Document, bool, bool]:
    """Insert or update a discovered document. Returns (document, is_new, metadata_changed)."""
    doc = session.scalars(
        select(Document).where(Document.source_id == item.source_key, Document.canonical_id == item.canonical_id)
    ).first()
    now = utcnow()
    values = {
        "department": item.department, "document_type": item.document_type, "document_number": item.document_number,
        "title": item.title, "publication_date": item.publication_date, "language": item.language,
        "original_url": item.document_url,
    }
    if doc is None:
        doc = Document(
            source_id=item.source_key, canonical_id=item.canonical_id, state=item.state,
            canonical_url=canonicalize_url(item.document_url), listing_url=item.listing_url,
            raw_metadata={"listing": item.raw, "first_run_id": run_id}, first_seen_at=now, last_seen_at=now, **values,
        )
        session.add(doc)
        session.flush()
        session.add(DocumentVersion(document_id=doc.id, version_number=1, change_type="discovered",
                                    metadata_snapshot=_snapshot(doc), crawl_run_id=run_id))
        return doc, True, False

    doc.last_seen_at = now
    changed = {}
    for k, v in values.items():
        # Do not let a seed list with an English title overwrite an official-portal Marathi title.
        if k == "title" and item.raw.get("provenance", {}).get("seed") and doc.title:
            continue
        if v is not None and getattr(doc, k) != v:
            changed[k] = {"old": str(getattr(doc, k)), "new": str(v)}
            setattr(doc, k, v)
    if changed:
        last = max((v.version_number for v in doc.versions), default=0)
        session.add(DocumentVersion(document_id=doc.id, version_number=last + 1, change_type="metadata_changed",
                                    pdf_sha256=doc.pdf_sha256, object_storage_key=doc.object_storage_key,
                                    metadata_snapshot={**_snapshot(doc), "changes": changed}, crawl_run_id=run_id))
    return doc, False, bool(changed)


def _load_checkpoint(session: Session, source_id: str, mode: str) -> CrawlCheckpoint | None:
    return session.scalars(
        select(CrawlCheckpoint).where(CrawlCheckpoint.source_id == source_id, CrawlCheckpoint.mode == mode)
    ).first()


def _save_checkpoint(source_id: str, mode: str, state: dict[str, Any], completed: bool) -> None:
    with session_scope() as s:
        cp = _load_checkpoint(s, source_id, mode)
        if cp is None:
            cp = CrawlCheckpoint(source_id=source_id, mode=mode)
            s.add(cp)
        cp.state, cp.completed, cp.updated_at = state, completed, utcnow()


def _record_error(run_id: str, error: dict[str, Any]) -> None:
    with session_scope() as s:
        run = s.get(CrawlRun, run_id)
        if run is not None:
            run.errors = [*(run.errors or []), error][-200:]


def run_crawl(
    source_key: str,
    mode: str = "incremental",
    *,
    max_pages: int | None = None,
    download: bool = True,
    download_limit: int | None = None,
    recheck_existing: bool = False,
    restart: bool = False,
    options_override: dict[str, Any] | None = None,
) -> str:
    """Run one crawl of a source. Returns the crawl_run id."""
    if mode not in ("incremental", "backfill"):
        raise ValueError("mode must be incremental or backfill")
    cfg = _source_cfg(source_key)
    if options_override:
        cfg = cfg.model_copy(update={"options": {**cfg.options, **options_override}})
    with session_scope() as s:
        sync_sources(s)
        run = CrawlRun(source_id=cfg.key, mode=mode, params={"max_pages": max_pages, "download": download,
                                                              "download_limit": download_limit, "restart": restart})
        s.add(run)
        s.flush()
        run_id = run.id
        cp = _load_checkpoint(s, cfg.key, mode)
        # Incremental runs always start at the newest page; backfill resumes unless finished/restarted.
        checkpoint = None
        if mode == "backfill" and cp and not restart and not cp.completed:
            checkpoint = cp.state
        id_space = {cfg.key}

    adapter = build_adapter(cfg, _client_factory(cfg.allowed_hosts))
    counts = {"discovered": 0, "new": 0, "changed": 0}
    queued = 0
    status = "completed"

    def is_known(canonical_id: str) -> bool:
        with session_scope() as s:
            return s.scalars(select(Document.id).where(Document.source_id.in_(id_space | {"mh_gr_portal"}),
                                                       Document.canonical_id == canonical_id)).first() is not None

    try:
        for item in adapter.discover_documents(
            mode=mode, checkpoint=checkpoint, max_pages=max_pages, is_known=is_known,
            save_checkpoint=lambda state, done: _save_checkpoint(cfg.key, mode, state, done),
        ):
            id_space.add(item.source_key)
            counts["discovered"] += 1
            DOCS_DISCOVERED.labels(source=cfg.key).inc()
            with session_scope() as s:
                if s.get(Source, item.source_key) is None:
                    sync_sources(s)
                doc, is_new, changed = upsert_discovered(s, item, run_id)
                doc_id = doc.id
                needs = doc.download_status in ("pending", "failed") or changed or recheck_existing
            counts["new"] += int(is_new)
            counts["changed"] += int(changed)
            if download and needs and (download_limit is None or queued < download_limit):
                queued += 1
                enqueue(download_document, doc_id, run_id)
    except Exception as exc:
        status = "failed"
        log(logger, logging.ERROR, "crawl failed", source=cfg.key, run_id=run_id, error=str(exc))
        _record_error(run_id, {"stage": "discovery", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        adapter.client.close()
        with session_scope() as s:
            run = s.get(CrawlRun, run_id)
            run.pages_fetched = getattr(adapter, "pages_fetched", 0)
            run.documents_discovered, run.documents_new = counts["discovered"], counts["new"]
            run.documents_changed = (run.documents_changed or 0) + counts["changed"]
            if status == "completed" and run.documents_failed:
                status = "partial"
            run.status, run.finished_at = status, utcnow()
            src = s.get(Source, cfg.key)
            src.last_checked_at = utcnow()
        CRAWL_RUNS.labels(source=cfg.key, mode=mode, status=status).inc()
        if status != "failed":
            LAST_CRAWL_SUCCESS.labels(source=cfg.key).set(time.time())
    return run_id


# --------------------------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------------------------

def _bump(run_id: str | None, **fields: int) -> None:
    if not run_id:
        return
    with session_scope() as s:
        s.execute(update(CrawlRun).where(CrawlRun.id == run_id).values(
            {getattr(CrawlRun, k): getattr(CrawlRun, k) + v for k, v in fields.items()}))


def _dead_letter(kind: str, doc: Document | None, error: str, attempts: int, payload: dict | None = None) -> None:
    with session_scope() as s:
        s.add(DeadLetter(kind=kind, source_id=doc.source_id if doc else None, document_id=doc.id if doc else None,
                         url=doc.original_url if doc else None, error=error, attempts=attempts, payload=payload or {}))


def download_document(document_id: str, run_id: str | None = None, extract: bool = True) -> str:
    """Download, validate and store a document's PDF. Returns the resulting download_status."""
    with session_scope() as s:
        doc = s.get(Document, document_id)
        if doc is None:
            raise KeyError(document_id)
        url, etag, last_mod = doc.original_url, doc.http_etag, doc.http_last_modified
        has_binary = doc.pdf_sha256 is not None and doc.object_storage_key is not None
        hosts = _hosts_for_document(doc)
        attempts = int((doc.raw_metadata or {}).get("download_attempts", 0)) + 1
        source_id, referer = doc.source_id, doc.listing_url

    client = _client_factory(hosts)
    tmp: Path | None = None
    try:
        result = client.download_pdf(url, etag=etag if has_binary else None,
                                     last_modified=last_mod if has_binary else None, referer=referer)
        if result.not_modified:
            with session_scope() as s:
                doc = s.get(Document, document_id)
                doc.last_seen_at = utcnow()
                doc.raw_metadata = {**doc.raw_metadata, "last_verified_at": utcnow().isoformat()}
            return "unchanged"
        tmp = result.path
        assert tmp is not None
        page_count = validate_pdf_file(tmp)
        sha = sha256_file(tmp)
        key = original_key(sha)
        get_store().put_file(key, tmp)  # write-once; identical binaries share one object
        DOWNLOAD_BYTES.labels(source=source_id).inc(result.size)

        with session_scope() as s:
            doc = s.get(Document, document_id)
            previous_sha = doc.pdf_sha256
            doc.http_etag, doc.http_last_modified = result.etag, result.last_modified
            doc.download_error = None
            doc.raw_metadata = {**doc.raw_metadata, "download_attempts": 0, "final_url": result.final_url,
                                "redirects": result.redirects, "content_type": result.content_type,
                                "last_verified_at": utcnow().isoformat()}
            if previous_sha == sha:
                doc.download_status = "downloaded"
                return "unchanged"
            last = max((v.version_number for v in doc.versions), default=0)
            s.add(DocumentVersion(
                document_id=doc.id, version_number=last + 1,
                change_type="binary_changed" if previous_sha else "initial_download",
                pdf_sha256=sha, object_storage_key=key, crawl_run_id=run_id,
                metadata_snapshot={**_snapshot(doc), "previous_sha256": previous_sha, "size": result.size,
                                   "etag": result.etag, "last_modified": result.last_modified},
            ))
            doc.pdf_sha256, doc.object_storage_key = sha, key
            doc.file_size_bytes, doc.page_count = result.size, page_count
            doc.download_status, doc.downloaded_at = "downloaded", utcnow()
            doc.extraction_status = "pending"
            s.flush()
            original = find_binary_duplicate(s, sha, doc.id)
            if original is not None:
                link_duplicate(s, doc, original)
            status = "changed" if previous_sha else "downloaded"
        DOCS_DOWNLOADED.labels(source=source_id).inc()
        _bump(run_id, documents_downloaded=1, **({"documents_changed": 1} if status == "changed" else {}))
        if extract:
            enqueue(extract_document, document_id)
        return status
    except (AccessDenied, NotAPDF, DownloadTooLarge, InvalidPDFError, FetchError) as exc:
        permanent = not getattr(exc, "retryable", False) or attempts >= MAX_DOWNLOAD_ATTEMPTS
        DOCS_FAILED.labels(source=source_id, stage="download").inc()
        with session_scope() as s:
            doc = s.get(Document, document_id)
            doc.download_status = "dead" if permanent else "failed"
            doc.download_error = f"{type(exc).__name__}: {exc}"
            doc.raw_metadata = {**doc.raw_metadata, "download_attempts": attempts}
        if permanent:
            with session_scope() as s:
                doc = s.get(Document, document_id)
            _dead_letter("download", doc, f"{type(exc).__name__}: {exc}", attempts, {"run_id": run_id})
        _bump(run_id, documents_failed=1)
        if run_id:
            _record_error(run_id, {"stage": "download", "document_id": document_id, "url": url, "error": str(exc)})
        log(logger, logging.WARNING, "download failed", document_id=document_id, url=url, error=str(exc), permanent=permanent)
        return "dead" if permanent else "failed"
    finally:
        client.close()
        if tmp is not None:
            tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------
# Extraction + OCR
# --------------------------------------------------------------------------------------------

def extract_document(document_id: str, allow_ocr: bool | None = None) -> str:
    from core.config.settings import get_settings
    from services import ocr
    from services.pdf_extraction import assess_text, extract_pages, guess_document_language

    settings = get_settings()
    allow_ocr = settings.ocr_enabled if allow_ocr is None else allow_ocr
    started = time.monotonic()
    with session_scope() as s:
        doc = s.get(Document, document_id)
        if doc is None or not doc.object_storage_key:
            raise ValueError(f"document {document_id} has no stored PDF")
        key, lang, state, sha = doc.object_storage_key, doc.language, doc.state, doc.pdf_sha256

    store = get_store()
    path = store.open_path(key)
    try:
        pages = extract_pages(path, lang, settings.ocr_min_chars_per_page)
        failed = [p.page_number for p in pages if not p.usable]
        ocr_note: dict[str, Any] = {}
        if failed and allow_ocr:
            try:
                ocr_pdf = ocr.run_ocrmypdf(path, failed, lang, state)
                try:
                    texts = ocr.read_pages(ocr_pdf, failed)
                    store.put_file(derived_key(sha, "ocr"), ocr_pdf)
                    ocr_note["derived_ocr_key"] = derived_key(sha, "ocr")
                finally:
                    ocr_pdf.unlink(missing_ok=True)
                for p in pages:
                    if p.page_number in texts:
                        ok, reason, prof = assess_text(texts[p.page_number], lang, settings.ocr_min_chars_per_page)
                        p.diagnostics["text_layer_reason"] = p.reason
                        p.text, p.method, p.usable, p.reason, p.script_profile = texts[p.page_number], "ocr:tesseract", ok, reason, prof
                        p.char_count = len(p.text.strip())
            except ocr.OCRUnavailable as exc:
                ocr_note["ocr_unavailable"] = str(exc)
            except Exception as exc:
                ocr_note["ocr_error"] = str(exc)[:1000]
        if failed and not allow_ocr:
            ocr_note["ocr_skipped"] = "OCR disabled by configuration"
        usable = sum(p.usable for p in pages)
        ocr_pending = bool({"ocr_unavailable", "ocr_skipped"} & ocr_note.keys())
        if usable == len(pages):
            status = "done"
        elif ocr_pending:
            status = "needs_ocr"  # retry with `grctl extract-pending` on an OCR-capable host
        else:
            status = "partial" if usable else "failed"
        detected = guess_document_language(pages, state)
        with session_scope() as s:
            doc = s.get(Document, document_id)
            s.query(DocumentPage).filter(DocumentPage.document_id == document_id).delete()
            for p in pages:
                s.add(DocumentPage(document_id=document_id, page_number=p.page_number, text=p.text,
                                   extraction_method=p.method, char_count=p.char_count, script_profile=p.script_profile,
                                   confidence=p.confidence, diagnostics={**p.diagnostics, "usable": p.usable, "reason": p.reason}))
            doc.extraction_status = status
            doc.page_count = len(pages)
            doc.raw_metadata = {**doc.raw_metadata, "extraction": {"usable_pages": usable, "pages": len(pages),
                                                                    "detected_language": detected, **ocr_note}}
            if doc.language is None and detected:
                doc.language = detected
        if status in ("failed", "needs_ocr"):
            DOCS_FAILED.labels(source=state, stage="extraction").inc()
        return status
    finally:
        EXTRACTION_SECONDS.observe(time.monotonic() - started)
        if not isinstance(store, LocalObjectStore):
            path.unlink(missing_ok=True)  # temp copy from remote storage; local paths are the originals
