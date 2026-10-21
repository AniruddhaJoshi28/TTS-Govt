from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
WINDOWS_INDIC_FONT = Path("C:/Windows/Fonts/Nirmala.ttc")
LINUX_INDIC_FONTS = [Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf")]


def fixture_html(name: str) -> str:
    return (FIXTURES / "html" / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own SQLite DB, object store and zero-delay crawler settings."""
    monkeypatch.setenv("GR_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}")
    monkeypatch.setenv("GR_STORAGE_BACKEND", "local")
    monkeypatch.setenv("GR_LOCAL_STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setenv("GR_REDIS_URL", "")
    monkeypatch.setenv("GR_MIN_REQUEST_INTERVAL_S", "0")
    monkeypatch.setenv("GR_BACKOFF_BASE_S", "0")
    monkeypatch.setenv("GR_MAX_RETRIES", "2")
    monkeypatch.setenv("GR_OBEY_ROBOTS_TXT", "false")
    monkeypatch.setenv("GR_OCR_ENABLED", "false")
    monkeypatch.setenv("GR_ADMIN_API_TOKEN", "test-admin-token")
    from core.config.settings import get_settings
    from core.database import session as db
    from core.storage import set_store
    from services.discovery import pipeline
    from services.discovery.queue import set_inline

    get_settings.cache_clear()
    db.configure()
    db.create_all()
    set_store(None)
    set_inline(True)
    pipeline.set_client_factory(None)
    yield
    set_inline(None)
    set_store(None)
    get_settings.cache_clear()


def make_pdf(path: Path, pages: list[str] | None = None, *, blank_pages: int = 0, fontfile: Path | None = None) -> Path:
    """Create a small valid PDF. ``pages`` text is drawn as real text; ``blank_pages`` have an image but no text."""
    import pymupdf

    doc = pymupdf.open()
    for text in pages or ["Government of Odisha Resolution No. 123 dated 01-01-2026 regarding test policy matters."]:
        page = doc.new_page()
        if fontfile:
            page.insert_font(fontname="indic", fontfile=str(fontfile))
            page.insert_text((50, 100), text, fontname="indic", fontsize=12)
        else:
            page.insert_text((50, 100), text, fontsize=12)
    for _ in range(blank_pages):
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
        pix.clear_with(200)
        page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def pdf_bytes(tmp_path: Path, name: str = "doc.pdf", **kw) -> bytes:
    return make_pdf(tmp_path / name, **kw).read_bytes()


def indic_font() -> Path | None:
    for p in [WINDOWS_INDIC_FONT, *LINUX_INDIC_FONTS]:
        if p.exists():
            return p
    return None


live = pytest.mark.skipif(os.environ.get("GR_LIVE_TESTS") != "1", reason="set GR_LIVE_TESTS=1 to hit real sites")
