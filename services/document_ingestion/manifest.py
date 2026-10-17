"""Document manifest: the curated list of documents a corpus is built from."""

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, HttpUrl

from schemas.api.envelope import Language, State

DEMO_MANIFEST = Path(__file__).parents[2] / "data" / "demo" / "documents.yaml"


class FetchSpec(BaseModel):
    method: str  # "direct" | "mp_labour_dms"
    path: str | None = None


class DocumentEntry(BaseModel):
    id: str
    state: State
    language: Language
    document_type: str
    issued: date
    department: str
    department_en: str
    title: str
    title_en: str
    url: HttpUrl
    listing_url: HttpUrl
    fetch: FetchSpec
    portal_metadata: dict[str, str] = {}


def load_manifest(path: Path = DEMO_MANIFEST) -> list[DocumentEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = [DocumentEntry.model_validate(d) for d in raw["documents"]]
    ids = [e.id for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate document ids in manifest")
    return entries
