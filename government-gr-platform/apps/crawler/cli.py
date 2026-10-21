"""Operator CLI: ``python -m apps.crawler.cli <command>`` (installed as ``grctl``)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from core.database.session import create_all, session_scope
from core.models import CrawlRun, DeadLetter, Document
from core.observability import setup_logging


def _print(obj) -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_init_db(args) -> None:
    create_all()
    from services.discovery.pipeline import sync_sources

    with session_scope() as s:
        sync_sources(s)
    _print({"ok": True})


def cmd_sources(args) -> None:
    from core.config.sources import load_sources

    _print([{"key": s.key, "state": s.state, "status": s.status, "active": s.active, "adapter": s.adapter} for s in load_sources()])


def _crawl(args, mode: str) -> None:
    from services.discovery.pipeline import run_crawl

    override = json.loads(args.options) if args.options else None
    run_id = run_crawl(args.source, mode, max_pages=args.max_pages, download=not args.no_download,
                       download_limit=args.download_limit, recheck_existing=getattr(args, "recheck", False),
                       restart=getattr(args, "restart", False), options_override=override)
    with session_scope() as s:
        run = s.get(CrawlRun, run_id)
        _print({k: getattr(run, k) for k in ("id", "source_id", "mode", "status", "pages_fetched", "documents_discovered",
                                              "documents_new", "documents_downloaded", "documents_changed", "documents_failed")}
               | {"errors": run.errors[-5:]})


def cmd_crawl(args) -> None:
    _crawl(args, "incremental")


def cmd_backfill(args) -> None:
    _crawl(args, "backfill")


def cmd_crawl_active(args) -> None:
    from core.config.sources import load_sources
    from services.discovery.pipeline import run_crawl

    out = {}
    for src in load_sources():
        if src.active and src.adapter:
            out[src.key] = run_crawl(src.key, "incremental", max_pages=args.max_pages, download_limit=args.download_limit)
    _print(out)


def cmd_download_pending(args) -> None:
    from services.discovery.pipeline import download_document

    with session_scope() as s:
        stmt = select(Document.id).where(Document.download_status.in_(["pending", "failed"]))
        if args.source:
            stmt = stmt.where(Document.source_id == args.source)
        ids = s.scalars(stmt.limit(args.limit)).all()
    _print({doc_id: download_document(doc_id) for doc_id in ids})


def cmd_extract_pending(args) -> None:
    from services.discovery.pipeline import extract_document

    with session_scope() as s:
        ids = s.scalars(select(Document.id).where(Document.download_status == "downloaded",
                                                  Document.extraction_status.in_(["pending", "failed", "needs_ocr"])).limit(args.limit)).all()
    _print({doc_id: extract_document(doc_id) for doc_id in ids})


def cmd_import(args) -> None:
    from services.discovery.manual_import import import_manifest

    _print(import_manifest(Path(args.manifest), args.operator))


def cmd_stats(args) -> None:
    with session_scope() as s:
        by_source = s.execute(select(Document.source_id, Document.download_status, func.count())
                              .group_by(Document.source_id, Document.download_status)).all()
        by_extract = s.execute(select(Document.extraction_status, func.count()).group_by(Document.extraction_status)).all()
        validated = s.scalar(select(func.count()).where(Document.pdf_sha256.is_not(None)))
        unique_bins = s.scalar(select(func.count(func.distinct(Document.pdf_sha256))))
        dead = s.scalar(select(func.count(DeadLetter.id)))
    _print({"by_source_status": [list(r) for r in by_source], "extraction": [list(r) for r in by_extract],
            "validated_pdfs": validated, "unique_binaries": unique_bins, "dead_letters": dead})


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    p = argparse.ArgumentParser(prog="grctl")
    sub = p.add_subparsers(required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("sources").set_defaults(fn=cmd_sources)
    for name, fn in (("crawl", cmd_crawl), ("backfill", cmd_backfill)):
        c = sub.add_parser(name)
        c.add_argument("source")
        c.add_argument("--max-pages", type=int)
        c.add_argument("--download-limit", type=int)
        c.add_argument("--no-download", action="store_true")
        c.add_argument("--options", help="JSON object overriding source options")
        if name == "crawl":
            c.add_argument("--recheck", action="store_true", help="conditional-GET already downloaded documents")
        else:
            c.add_argument("--restart", action="store_true", help="ignore checkpoint and start over")
        c.set_defaults(fn=fn)
    c = sub.add_parser("crawl-active")
    c.add_argument("--max-pages", type=int)
    c.add_argument("--download-limit", type=int)
    c.set_defaults(fn=cmd_crawl_active)
    c = sub.add_parser("download-pending")
    c.add_argument("--source")
    c.add_argument("--limit", type=int, default=100)
    c.set_defaults(fn=cmd_download_pending)
    c = sub.add_parser("extract-pending")
    c.add_argument("--limit", type=int, default=100)
    c.set_defaults(fn=cmd_extract_pending)
    c = sub.add_parser("import-manual")
    c.add_argument("manifest")
    c.add_argument("--operator", required=True)
    c.set_defaults(fn=cmd_import)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
