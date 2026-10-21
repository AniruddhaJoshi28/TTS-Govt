"""Runtime configuration, loaded from environment variables (prefix ``GR_``) or ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GR_", env_file=".env", extra="ignore")

    # Database: PostgreSQL in production; SQLite is supported for local development and tests.
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'gr_platform.sqlite3').as_posix()}"

    # Object storage: "minio" or "local".
    storage_backend: str = "local"
    local_storage_dir: Path = PROJECT_ROOT / "data" / "objects"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "gov-documents"

    # Queue: when redis_url is empty, jobs run inline in the calling process.
    redis_url: str = ""
    queue_name: str = "gr-default"

    # Crawling etiquette.
    user_agent: str = "GovGRArchiveBot/0.1 (+self-hosted public-records archive; contact: admin@localhost)"
    request_timeout_s: float = 45.0
    min_request_interval_s: float = 2.0
    max_retries: int = 4
    backoff_base_s: float = 2.0
    backoff_max_s: float = 120.0
    max_pdf_bytes: int = 80 * 1024 * 1024
    obey_robots_txt: bool = True

    sources_file: Path = PROJECT_ROOT / "configs" / "sources.yaml"

    # API
    admin_api_token: str = Field(default="change-me", description="Bearer token for crawl admin endpoints")
    api_page_size_max: int = 200

    # OCR
    ocr_enabled: bool = True
    ocr_min_chars_per_page: int = 40


@lru_cache
def get_settings() -> Settings:
    return Settings()
