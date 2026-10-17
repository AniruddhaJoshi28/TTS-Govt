"""Loads and validates the official source registry."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, HttpUrl, model_validator

from schemas.api.envelope import Language, State

DEFAULT_PATH = Path(__file__).with_name("sources.yaml")


class Source(BaseModel):
    id: str
    state: State
    name: str
    base_url: HttpUrl | None
    document_types: list[str]
    languages: list[Language]
    crawl_method: Literal["http", "browser", "undecided"]
    verified: bool
    terms_reviewed: bool
    notes: str = ""

    @model_validator(mode="after")
    def verified_requires_url(self) -> "Source":
        if self.verified and self.base_url is None:
            raise ValueError(f"source {self.id!r} is marked verified but has no base_url")
        return self

    @property
    def crawlable(self) -> bool:
        """A crawler may only touch sources that are confirmed official and permitted."""
        return (
            self.verified
            and self.terms_reviewed
            and self.base_url is not None
            and self.crawl_method != "undecided"
        )


def load_sources(path: Path = DEFAULT_PATH) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = [Source.model_validate(entry) for entry in raw["sources"]]
    ids = [s.id for s in sources]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate source ids: {sorted(duplicates)}")
    return sources
