"""FastAPI retrieval + admin API."""

from __future__ import annotations

import datetime as dt
import hmac
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Response, Security
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from core.config.settings import get_settings
from core.config.sources import load_sources
from core.database.session import get_sessionmaker
from core.models import CrawlRun, Document, DocumentPage, Source
from core.schemas import CrawlRunOut, DocumentOut, PageOut, SourceOut
from core.storage import LocalObjectStore, get_store
from services.search import DocumentFilters, list_documents, search_documents

@asynccontextmanager
async def lifespan(_: FastAPI):
    from core.database.session import create_all, session_scope
    from core.observability import setup_logging
    from services.discovery.pipeline import sync_sources

    setup_logging()
    if get_settings().database_url.startswith("sqlite"):
        create_all()  # PostgreSQL deployments use `alembic upgrade head`
    with session_scope() as s:
        sync_sources(s)
    yield


app = FastAPI(title="Government GR Platform", version="0.1.0", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def require_admin(creds: HTTPAuthorizationCredentials | None = Security(bearer)) -> None:
    token = get_settings().admin_api_token
    if creds is None or not hmac.compare_digest(creds.credentials, token):
        raise HTTPException(status_code=401, detail="admin token required", headers={"WWW-Authenticate": "Bearer"})


def filters(
    state: str | None = None,
    department: str | None = None,
    document_type: str | None = None,
    language: str | None = None,
    document_number: str | None = None,
    source_id: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> DocumentFilters:
    return DocumentFilters(state, department, document_type, language, document_number, source_id, date_from, date_to)


def paging(limit: Annotated[int, Query(ge=1)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> tuple[int, int]:
    return min(limit, get_settings().api_page_size_max), offset


DB = Annotated[Session, Depends(db)]


@app.get("/health")
def health(session: DB) -> dict:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "documents": session.scalar(select(func.count(Document.id)))}


@app.get("/sources", response_model=list[SourceOut])
def sources(session: DB):
    return session.scalars(select(Source).order_by(Source.state, Source.id)).all()


@app.get("/sources/{source_id}", response_model=SourceOut)
def source(source_id: str, session: DB):
    row = session.get(Source, source_id)
    if row is None:
        raise HTTPException(404, "source not found")
    return row


@app.get("/documents")
def documents(session: DB, f: Annotated[DocumentFilters, Depends(filters)], p: Annotated[tuple[int, int], Depends(paging)]):
    rows, total = list_documents(session, f, *p)
    return {"items": [DocumentOut.model_validate(r) for r in rows], "total": total, "limit": p[0], "offset": p[1]}


@app.get("/documents/search")
def search(session: DB, q: Annotated[str, Query(min_length=2)], f: Annotated[DocumentFilters, Depends(filters)],
           p: Annotated[tuple[int, int], Depends(paging)]):
    results, total = search_documents(session, q, f, *p)
    return {
        "items": [{"document": DocumentOut.model_validate(r["document"]), "snippet": r["snippet"], "page_number": r["page_number"]}
                  for r in results],
        "total": total, "limit": p[0], "offset": p[1],
    }


@app.get("/documents/{document_id}")
def document(document_id: str, session: DB):
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return {
        **DocumentOut.model_validate(doc).model_dump(),
        "provenance": {"listing_url": doc.listing_url, "original_url": doc.original_url, "canonical_url": doc.canonical_url,
                       "etag": doc.http_etag, "last_modified": doc.http_last_modified, "raw": doc.raw_metadata},
        "versions": [{"version": v.version_number, "change_type": v.change_type, "sha256": v.pdf_sha256,
                      "created_at": v.created_at, "crawl_run_id": v.crawl_run_id} for v in doc.versions],
    }


@app.get("/documents/{document_id}/download")
def download(document_id: str, session: DB):
    doc = session.get(Document, document_id)
    if doc is None or not doc.object_storage_key:
        raise HTTPException(404, "PDF not available")
    store = get_store()
    filename = f"{doc.state}-{doc.canonical_id.rsplit('/', 1)[-1].removesuffix('.pdf')}.pdf".replace('"', "")
    headers = {"X-Content-SHA256": doc.pdf_sha256 or "", "X-Original-URL": doc.original_url}
    if isinstance(store, LocalObjectStore):
        return FileResponse(store.open_path(doc.object_storage_key), media_type="application/pdf", filename=filename, headers=headers)
    stream = store.stream(doc.object_storage_key)  # type: ignore[attr-defined]
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@app.get("/documents/{document_id}/pages", response_model=list[PageOut])
def pages(document_id: str, session: DB):
    if session.get(Document, document_id) is None:
        raise HTTPException(404, "document not found")
    return session.scalars(select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)).all()


@app.get("/crawl/runs")
def runs(session: DB, p: Annotated[tuple[int, int], Depends(paging)], source_id: str | None = None):
    stmt = select(CrawlRun)
    if source_id:
        stmt = stmt.where(CrawlRun.source_id == source_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.order_by(CrawlRun.started_at.desc()).limit(p[0]).offset(p[1])).all()
    return {"items": [CrawlRunOut.model_validate(r) for r in rows], "total": total, "limit": p[0], "offset": p[1]}


@app.get("/crawl/runs/{run_id}", response_model=CrawlRunOut)
def run(run_id: str, session: DB):
    row = session.get(CrawlRun, run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    return row


class CrawlRequest(BaseModel):
    source_id: str
    max_pages: int | None = None
    download: bool = True
    download_limit: int | None = None
    restart: bool = False


def _dispatch(mode: str, req: CrawlRequest, background: BackgroundTasks) -> dict:
    keys = {s.key: s for s in load_sources()}
    cfg = keys.get(req.source_id)
    if cfg is None:
        raise HTTPException(404, "unknown source")
    if not cfg.adapter:
        raise HTTPException(409, f"source has no adapter (audit status {cfg.status})")
    from services.discovery.pipeline import run_crawl

    kwargs = dict(mode=mode, max_pages=req.max_pages, download=req.download, download_limit=req.download_limit, restart=req.restart)
    settings = get_settings()
    if settings.redis_url:
        from redis import Redis
        from rq import Queue

        job = Queue(settings.queue_name, connection=Redis.from_url(settings.redis_url)).enqueue(
            run_crawl, req.source_id, job_timeout=6 * 3600, **kwargs)
        return {"queued": True, "job_id": job.id, "mode": mode}
    background.add_task(run_crawl, req.source_id, **kwargs)
    return {"queued": True, "job_id": None, "mode": mode, "note": "running in API background task (no Redis configured)"}


@app.post("/crawl/start", dependencies=[Depends(require_admin)], status_code=202)
def crawl_start(req: CrawlRequest, background: BackgroundTasks):
    return _dispatch("incremental", req, background)


@app.post("/crawl/backfill", dependencies=[Depends(require_admin)], status_code=202)
def crawl_backfill(req: CrawlRequest, background: BackgroundTasks):
    return _dispatch("backfill", req, background)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


