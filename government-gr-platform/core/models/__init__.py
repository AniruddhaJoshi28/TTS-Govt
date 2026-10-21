"""ORM models. Portable between PostgreSQL and SQLite (JSON columns use the generic JSON type)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # = source key from sources.yaml
    state: Mapped[str] = mapped_column(String(32), index=True)
    department: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(64))
    crawl_strategy: Mapped[str] = mapped_column(String(64))
    access_policy: Mapped[str] = mapped_column(Text, default="")
    audit_status: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Canonical identity: one row per (source, canonical document id).
        UniqueConstraint("source_id", "canonical_id", name="uq_documents_source_canonical"),
        Index("ix_documents_state_date", "state", "publication_date"),
        Index("ix_documents_sha256", "pdf_sha256"),
        Index("ix_documents_number", "document_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    canonical_id: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32))
    department: Mapped[str | None] = mapped_column(String(255), index=True)
    document_type: Mapped[str] = mapped_column(String(48), index=True)
    document_number: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    publication_date: Mapped[dt.date | None] = mapped_column(Date)
    language: Mapped[str | None] = mapped_column(String(16), index=True)
    original_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    listing_url: Mapped[str | None] = mapped_column(Text)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    object_storage_key: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    http_etag: Mapped[str | None] = mapped_column(String(255))
    http_last_modified: Mapped[str | None] = mapped_column(String(64))
    download_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    download_error: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    downloaded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source] = relationship()
    pages: Mapped[list[DocumentPage]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_number"
    )


class DocumentVersion(Base):
    """Immutable history of binary and metadata changes for a document."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_document_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(32))  # initial | binary_changed | metadata_changed
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    object_storage_key: Mapped[str | None] = mapped_column(Text)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    crawl_run_id: Mapped[str | None] = mapped_column(ForeignKey("crawl_runs.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="versions")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    mode: Mapped[str] = mapped_column(String(16))  # incremental | backfill
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    documents_discovered: Mapped[int] = mapped_column(Integer, default=0)
    documents_new: Mapped[int] = mapped_column(Integer, default=0)
    documents_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    documents_changed: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CrawlCheckpoint(Base):
    __tablename__ = "crawl_checkpoints"
    __table_args__ = (UniqueConstraint("source_id", "mode", name="uq_checkpoint_source_mode"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    mode: Mapped[str] = mapped_column(String(16))
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_document_page"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    extraction_method: Mapped[str] = mapped_column(String(32))  # pymupdf | pypdf | ocr:tesseract
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    script_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="pages")


class DocumentRelationship(Base):
    __tablename__ = "document_relationships"
    __table_args__ = (
        UniqueConstraint("from_document_id", "to_document_id", "relation_type", name="uq_document_relationship"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    from_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    to_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(32))  # duplicate_binary | amends | supersedes | references
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeadLetter(Base):
    """Permanently failed work items, kept for inspection and manual replay."""

    __tablename__ = "dead_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32))  # download | extraction | listing
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36))
    url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
