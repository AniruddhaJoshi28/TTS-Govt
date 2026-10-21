"""Deduplication rules.

1. Identity: (source_id, canonical_id) is unique — the same listing entry is one document.
2. Binary duplicates: identical SHA-256 across *different* documents are linked with a
   ``duplicate_binary`` relationship and ``duplicate_of_id``; the original object is stored once.
3. Titles are never used for deduplication (government titles repeat legitimately).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Document, DocumentRelationship


def find_binary_duplicate(session: Session, sha256: str, exclude_id: str) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.pdf_sha256 == sha256, Document.id != exclude_id, Document.duplicate_of_id.is_(None))
        .order_by(Document.first_seen_at)
        .limit(1)
    )
    return session.scalars(stmt).first()


def link_duplicate(session: Session, doc: Document, original: Document) -> None:
    doc.duplicate_of_id = original.id
    exists = session.scalars(
        select(DocumentRelationship).where(
            DocumentRelationship.from_document_id == doc.id,
            DocumentRelationship.to_document_id == original.id,
            DocumentRelationship.relation_type == "duplicate_binary",
        )
    ).first()
    if not exists:
        session.add(DocumentRelationship(
            from_document_id=doc.id, to_document_id=original.id, relation_type="duplicate_binary",
            evidence={"sha256": doc.pdf_sha256, "from_url": doc.canonical_url, "to_url": original.canonical_url},
        ))
