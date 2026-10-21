"""Document search over metadata and page text.

PostgreSQL: uses ``ILIKE`` on title + page text (Unicode-safe for Indic scripts; ``to_tsvector('simple', ...)``
can be added via a GIN index migration when corpus size warrants). SQLite: ``LIKE`` (case-insensitive for ASCII).
Language-specific stemming is intentionally avoided: there is no reliable open-source stemmer for
Marathi/Odia, and exact-substring matching preserves official wording.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from core.models import Document, DocumentPage


@dataclass
class DocumentFilters:
    state: str | None = None
    department: str | None = None
    document_type: str | None = None
    language: str | None = None
    document_number: str | None = None
    source_id: str | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None


def apply_filters(stmt: Select, f: DocumentFilters) -> Select:
    if f.state:
        stmt = stmt.where(Document.state == f.state)
    if f.department:
        stmt = stmt.where(Document.department.ilike(f"%{f.department}%"))
    if f.document_type:
        stmt = stmt.where(Document.document_type == f.document_type)
    if f.language:
        stmt = stmt.where(Document.language == f.language)
    if f.document_number:
        stmt = stmt.where(Document.document_number.ilike(f"%{f.document_number}%"))
    if f.source_id:
        stmt = stmt.where(Document.source_id == f.source_id)
    if f.date_from:
        stmt = stmt.where(Document.publication_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Document.publication_date <= f.date_to)
    return stmt


def list_documents(session: Session, f: DocumentFilters, limit: int, offset: int) -> tuple[list[Document], int]:
    base = apply_filters(select(Document), f)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(base.order_by(Document.publication_date.desc().nulls_last(), Document.first_seen_at.desc())
                           .limit(limit).offset(offset)).all()
    return list(rows), total


def search_documents(session: Session, q: str, f: DocumentFilters, limit: int, offset: int) -> tuple[list[dict], int]:
    pattern = f"%{q}%"
    page_hit = select(DocumentPage.document_id).where(DocumentPage.text.ilike(pattern))
    base = apply_filters(select(Document), f).where(
        or_(Document.title.ilike(pattern), Document.document_number.ilike(pattern), Document.id.in_(page_hit))
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    docs = session.scalars(base.order_by(Document.publication_date.desc().nulls_last()).limit(limit).offset(offset)).all()
    results = []
    for d in docs:
        snippet, page_no = None, None
        hit = session.scalars(select(DocumentPage).where(DocumentPage.document_id == d.id, DocumentPage.text.ilike(pattern))
                              .order_by(DocumentPage.page_number).limit(1)).first()
        if hit:
            idx = hit.text.lower().find(q.lower())
            start = max(0, idx - 120)
            snippet, page_no = " ".join(hit.text[start: idx + len(q) + 120].split()), hit.page_number
        results.append({"document": d, "snippet": snippet, "page_number": page_no})
    return results, total
