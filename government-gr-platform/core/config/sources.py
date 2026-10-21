"""Loads and validates ``configs/sources.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from core.config.settings import get_settings

SOURCE_STATUSES = {
    "VERIFIED_WORKING",
    "PARTIALLY_WORKING",
    "REQUIRES_MANUAL_ACCESS",
    "BLOCKED_BY_POLICY",
    "UNAVAILABLE",
    "NOT_YET_TESTED",
}


class SourceConfig(BaseModel):
    key: str
    state: str
    department: str | None = None
    name: str
    base_url: str
    adapter: str | None = None
    source_type: str
    crawl_strategy: str
    access_policy: str = ""
    allowed_hosts: list[str]
    status: str
    active: bool = False
    schedule_cron: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"{self.key}: unknown status {self.status}")


def load_sources(path: Path | None = None) -> list[SourceConfig]:
    path = path or get_settings().sources_file
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    sources = [SourceConfig(**item) for item in raw["sources"]]
    keys = [s.key for s in sources]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source keys in sources.yaml")
    return sources


def get_source(key: str, path: Path | None = None) -> SourceConfig:
    for source in load_sources(path):
        if source.key == key:
            return source
    raise KeyError(key)
