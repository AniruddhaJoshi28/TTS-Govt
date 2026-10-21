from __future__ import annotations

import csv
import json

from sqlalchemy import select

from apps.crawler import cli
from core.database.session import session_scope
from core.models import Document
from tests.conftest import make_pdf

FIELDS = ["file", "source_key", "canonical_id", "title", "department", "document_type", "document_number",
          "publication_date", "language", "original_url"]


def write_manifest(tmp_path, rows):
    path = tmp_path / "manifest.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def test_manual_import_with_provenance(tmp_path, capsys):
    make_pdf(tmp_path / "cab.pdf", ["Cabinet decision text"])
    (tmp_path / "bad.pdf").write_bytes(b"not a pdf at all" * 50)
    manifest = write_manifest(tmp_path, [
        {"file": "cab.pdf", "source_key": "od_cabinet", "canonical_id": "cab-2026-10-01", "title": "ମନ୍ତ୍ରିମଣ୍ଡଳ ନିଷ୍ପତ୍ତି",
         "department": "Cabinet Secretariat", "document_type": "cabinet_decision", "document_number": "C-1",
         "publication_date": "01-10-2026", "language": "or", "original_url": "https://cabinet.odisha.gov.in/x.pdf"},
        {"file": "bad.pdf", "source_key": "od_cabinet", "canonical_id": "bad", "title": "bad", "department": "",
         "document_type": "other", "document_number": "", "publication_date": "", "language": "", "original_url": "https://cabinet.odisha.gov.in/b.pdf"},
    ])
    cli.main(["import-manual", str(manifest), "--operator", "tester"])
    assert json.loads(capsys.readouterr().out) == {"imported": 1, "unchanged": 0, "invalid": 1}
    with session_scope() as s:
        doc = s.scalars(select(Document)).one()
        assert doc.state == "odisha" and doc.title == "ମନ୍ତ୍ରିମଣ୍ଡଳ ନିଷ୍ପତ୍ତି" and doc.download_status == "downloaded"
        assert doc.raw_metadata["listing"]["provenance"] == {"method": "manual", "operator": "tester", "file": "cab.pdf"}
        assert [v.change_type for v in doc.versions] == ["discovered", "manual_import"]
    cli.main(["import-manual", str(manifest), "--operator", "tester"])  # idempotent
    assert json.loads(capsys.readouterr().out)["unchanged"] == 1


def test_cli_init_sources_stats_extract(tmp_path, capsys):
    cli.main(["init-db"])
    cli.main(["sources"])
    capsys.readouterr()
    make_pdf(tmp_path / "x.pdf", ["Some resolution text that is long enough to be usable for extraction checks."])
    write_manifest(tmp_path, [{"file": "x.pdf", "source_key": "od_stsc_resolutions", "canonical_id": "/x.pdf", "title": "Resolution X",
                               "department": "", "document_type": "resolution", "document_number": "1", "publication_date": "2026-10-01",
                               "language": "en", "original_url": "https://stsc.odisha.gov.in/x.pdf"}])
    cli.main(["import-manual", str(tmp_path / "manifest.csv"), "--operator", "t"])
    cli.main(["extract-pending"])
    capsys.readouterr()
    cli.main(["stats"])
    stats = json.loads(capsys.readouterr().out)
    assert stats["validated_pdfs"] == 1 and stats["extraction"] == [["done", 1]]
