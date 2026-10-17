"""Shared response envelope for every /api/v1 endpoint (plan §5).

Every response carries a request ID, the selected language, source document
identifiers with version information, uncertainty signals and error details
that never expose internal secrets.
"""

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, HttpUrl

T = TypeVar("T")


class Language(StrEnum):
    MARATHI = "mr"
    HINDI = "hi"
    ODIA = "or"
    ENGLISH = "en"


class State(StrEnum):
    MAHARASHTRA = "MH"
    MADHYA_PRADESH = "MP"
    ODISHA = "OD"


class SourceRef(BaseModel):
    """A citation. It must resolve to a real stored document version and passage."""

    document_id: str
    version_id: str
    url: HttpUrl
    page: int | None = Field(default=None, ge=1)
    passage_id: str | None = None


class Uncertainty(BaseModel):
    """Something the answer could not establish, e.g. a missing deadline or stale source."""

    code: str
    message: str


class ErrorDetail(BaseModel):
    """Client-safe error. Never put stack traces, hostnames or credentials here."""

    code: str
    message: str
    retryable: bool = False


class Envelope(BaseModel, Generic[T]):
    request_id: str
    language: Language
    data: T | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    error: ErrorDetail | None = None
