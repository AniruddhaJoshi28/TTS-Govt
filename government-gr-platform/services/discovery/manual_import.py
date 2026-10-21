"""Lawful manual-import workflow for sources that need human interaction (CAPTCHA, login, broken TLS).

An operator downloads PDFs in a normal browser and records provenance in a CSV manifest:

    file,source_key,canonical_id,title,department,document_type,document_number,publication_date,language,original_url

The importer validates each PDF, stores it content-addressed, and records ``raw.provenance.method = manual``.
"""

from __future__ import annotations

import csv
from pathlib import Path

from core.database.session import session_scope
from core.models import DocumentVersion, Source, utcnow
from core.schemas import DiscoveredDocument
from core.storage import get_store, original_key
from core.validation import sha256_file, validate_pdf_file
from services.deduplication import find_binary_duplicate, link_duplicate
from services.discovery.pipeline import sync_sources, upsert_discovered
from services.metadata import parse_date


def import_manifest(manifest: Path, operator: str) -> dict[str, int]:
    stats = {"imported": 0, "unchanged": 0, "invalid": 0}
    base = manifest.parent
    with open(manifest, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with session_scope() as s:
        sync_sources(s)
    for row in rows:
        pdf = (base / row["file"]).resolve()
        try:
            pages = validate_pdf_file(pdf)
        except Exception:
            stats["invalid"] += 1
            continue
        sha = sha256_file(pdf)
        get_store().put_file(original_key(sha), pdf)
        item = DiscoveredDocument(
            source_key=row["source_key"], canonical_id=row["canonical_id"], state=row.get("state") or "",
            department=row.get("department") or None, document_type=row.get("document_type") or "other",
            document_number=row.get("document_number") or None, title=row["title"],
            publication_date=parse_date(row.get("publication_date")), language=row.get("language") or None,
            document_url=row["original_url"], raw={"provenance": {"method": "manual", "operator": operator, "file": row["file"]}},
        )
        with session_scope() as s:
            src = s.get(Source, item.source_key)
            if src is None:
                raise ValueError(f"unknown source_key {item.source_key}")
            item = item.model_copy(update={"state": item.state or src.state})
            doc, _, _ = upsert_discovered(s, item, None)
            if doc.pdf_sha256 == sha:
                stats["unchanged"] += 1
                continue
            last = max((v.version_number for v in doc.versions), default=0)
            s.add(DocumentVersion(document_id=doc.id, version_number=last + 1, change_type="manual_import",
                                  pdf_sha256=sha, object_storage_key=original_key(sha),
                                  metadata_snapshot={"operator": operator, "file": row["file"]}))
            doc.pdf_sha256, doc.object_storage_key, doc.page_count = sha, original_key(sha), pages
            doc.file_size_bytes, doc.download_status, doc.downloaded_at = pdf.stat().st_size, "downloaded", utcnow()
            doc.extraction_status = "pending"
            s.flush()
            dup = find_binary_duplicate(s, sha, doc.id)
            if dup:
                link_duplicate(s, doc, dup)
            stats["imported"] += 1
    return stats

