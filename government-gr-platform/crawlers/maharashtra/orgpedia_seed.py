"""Maharashtra historical backfill seeded from Orgpedia (https://github.com/orgpedia, MIT licence).

Orgpedia's per-department repos publish ``import/documents/documents.json`` with, per GR:
``url`` (official gr.maharashtra.gov.in PDF URL), ``code``, ``date``, ``dept``, ``text`` (English listing title).

We use this purely as a *seed list of identifiers*. Every PDF is downloaded from the official
government server and validated; Orgpedia-derived fields are recorded in ``raw.provenance``.
Each repo is one "listing page"; the checkpoint records which repos are done.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from core.schemas import DiscoveredDocument
from crawlers.base.adapter import ListingPage, SourceAdapter
from crawlers.maharashtra.gr_portal import CODE_RE, canonical_pdf_url
from services.metadata import clean_text, normalize_department, parse_date


class MaharashtraOrgpediaSeedAdapter(SourceAdapter):
    name = "maharashtra_orgpedia_seed"

    def initial_state(self, mode: str) -> dict[str, Any]:
        return {"repo_index": 0}

    def _repo_url(self, repo: str) -> str:
        branch = self.options.get("branch", "main")
        path = self.options.get("documents_path", "import/documents/documents.json")
        return f"https://raw.githubusercontent.com/orgpedia/{repo}/{branch}/{path}"

    def iter_listing_pages(self, state: dict[str, Any], mode: str) -> Iterator[ListingPage]:
        repos: list[str] = list(self.options.get("repos", []))
        idx = int(state.get("repo_index", 0))
        while idx < len(repos):
            url = self._repo_url(repos[idx])
            resp = self.client.get_text(url)
            yield ListingPage(url=url, html=resp.text, page_index=idx, next_state={"repo_index": idx + 1},
                              is_last=idx + 1 >= len(repos), extra={"repo": repos[idx]})
            idx += 1

    def extract_listing_metadata(self, listing: ListingPage) -> list[dict[str, Any]]:
        data = json.loads(listing.html)
        items = data.values() if isinstance(data, dict) else data
        rows = [dict(item) for item in items if isinstance(item, dict) and CODE_RE.match(str(item.get("code", "")))]
        limit = self.options.get("limit_per_repo")
        return rows[: int(limit)] if limit else rows

    def resolve_document_url(self, row: dict[str, Any], listing: ListingPage) -> str:
        # Always rebuild from the code: never trust a third-party URL as the download target.
        return canonical_pdf_url(row["code"])

    def normalize_metadata(self, row: dict[str, Any], document_url: str, listing: ListingPage) -> DiscoveredDocument:
        return DiscoveredDocument(
            source_key="mh_gr_portal",  # same canonical identity space as the live portal
            canonical_id=row["code"],
            state="maharashtra",
            department=normalize_department(row.get("dept")),
            document_type="government_resolution",
            document_number=row["code"],
            title=clean_text(row.get("text")) or row["code"],
            publication_date=parse_date(row.get("date")),
            language="mr",
            document_url=document_url,
            listing_url="https://gr.maharashtra.gov.in/1145/Government-Resolutions",
            raw={
                "provenance": {"seed": "orgpedia", "seed_url": listing.url, "repo": listing.extra.get("repo"),
                               "seed_listed_url": row.get("url"), "title_language": "en"},
                "size_kb": row.get("size_kb"),
                "num_pages_seed": row.get("num_pages"),
            },
        )
