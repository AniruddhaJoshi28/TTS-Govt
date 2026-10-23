"""Import documents archived by government-gr-platform (the crawler) into the assistant corpus.

    python scripts/import_crawled.py                       # all downloaded docs not yet imported
    python scripts/import_crawled.py --state MH --limit 20
    python scripts/import_crawled.py --reload-url http://127.0.0.1:8000/api/v1/reload

The crawler's SQLite DB and local object store are read directly (no platform imports: both projects
have a top-level ``services`` package). Pages the crawler flagged as unusable (no text layer, broken
ToUnicode maps, Devanagari glyph-order errors) are OCR'd instead of trusting the embedded text.
Documents that need OCR are skipped when Tesseract or its language data is missing, rather than
being imported with corrupt or empty text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.document_ingestion.crawled_import import (  # noqa: E402,F401  (re-exported for callers/tests)
    PLATFORM, STATE_MAP, corpus_id, entry_for, import_crawled, unusable_pages, upload_month)

def warm_summaries(app_url: str, docs: list[tuple[str, str]]) -> None:
    """Generate each new GR's summary in its own language now, so the first click in the UI is a cache hit."""
    for doc_id, lang in docs:
        body = json.dumps({"document_id": doc_id, "language": lang}).encode()
        req = urllib.request.Request(f"{app_url.rstrip('/')}/api/v1/summaries", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-API-Key": os.environ.get("API_KEY", "")})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                status = json.loads(resp.read()).get("data", {}).get("status")
            print(f"  summary {doc_id} ({lang}): {status}")
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read()).get("error") or {}
            except ValueError:
                err = {}
            print(f"  summary {doc_id} ({lang}) not pre-generated: HTTP {exc.code} "
                  f"{err.get('code', '')}: {err.get('message', '')}", file=sys.stderr)
            if err.get("code") in ("model_not_configured", "model_unavailable"):
                return  # model server down: the UI generates summaries on demand instead
        except Exception as exc:
            print(f"  summary {doc_id} ({lang}) not pre-generated: {exc}", file=sys.stderr)
            return


def reload_app(url: str) -> None:
    req = urllib.request.Request(url, method="POST", headers={"X-API-Key": os.environ.get("API_KEY", "")})
    with urllib.request.urlopen(req, timeout=60) as resp:
        print("app reloaded:", resp.read().decode()[:200])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--platform-db", type=Path, default=PLATFORM / "data" / "gr_platform.sqlite3")
    ap.add_argument("--objects", type=Path, default=PLATFORM / "data" / "objects")
    ap.add_argument("--corpus", type=Path, default=Path(os.environ.get("CORPUS_DIR", ROOT / "data" / "corpus")))
    ap.add_argument("--state", choices=[s.value for s in STATE_MAP.values()])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--reload-url", help="POST here afterwards so a running app picks up the new documents")
    ap.add_argument("--warm-url", help="app base URL: pre-generate summaries of newly imported GRs")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        stats, imported = import_crawled(args.platform_db, args.objects, args.corpus, args.state, args.limit)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(stats, indent=2))
    if args.reload_url and stats["imported"]:
        reload_app(args.reload_url)
    if args.warm_url and imported:
        warm_summaries(args.warm_url, imported)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
