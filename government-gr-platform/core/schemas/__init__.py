"""Pydantic schemas shared by crawlers, pipeline and API."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

DOCUMENT_TYPES = {
    "government_resolution",
    "resolution",
    "circular",
    "order",
    "office_order",
    "notification",
    "gazette",
    "cabinet_decision",
    "memorandum",
    "letter",
    "other",
}


class DiscoveredDocument(BaseModel):
    """A document as seen on a listing page, before download. Produced by every adapter."""

    source_key: str
    canonical_id: str = Field(description="Stable per-source identifier (e.g. MH unique code, URL path)")
    state: str
    department: str | None = None
    document_type: str = "other"
    document_number: str | None = None
    title: str
    publication_date: dt.date | None = None
    language: str | None = None
    document_url: str
    listing_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in DOCUMENT_TYPES:
            raise ValueError(f"unknown document_type {v!r}")
        return v

    @field_validator("title")
    @classmethod
    def _non_empty_title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("empty title")
        return v


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    canonical_id: str
    state: str
    department: str | None
    document_type: str
    document_number: str | None
    title: str
    publication_date: dt.date | None
    language: str | None
    original_url: str
    canonical_url: str
    listing_url: str | None
    pdf_sha256: str | None
    file_size_bytes: int | None
    page_count: int | None
    download_status: str
    extraction_status: str
    duplicate_of_id: str | None
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    text: str
    extraction_method: str
    char_count: int
    script_profile: dict[str, Any]
    confidence: float | None
    diagnostics: dict[str, Any]


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    state: str
    department: str | None
    name: str
    base_url: str
    source_type: str
    crawl_strategy: str
    access_policy: str
    audit_status: str
    active: bool
    last_checked_at: dt.datetime | None


class CrawlRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    mode: str
    status: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    pages_fetched: int
    documents_discovered: int
    documents_new: int
    documents_downloaded: int
    documents_changed: int
    documents_failed: int
    errors: list[dict[str, Any]]
    params: dict[str, Any]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
