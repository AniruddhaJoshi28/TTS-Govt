# Implementation Status

**As of:** 2026-10-21. Every number on this page comes from commands run on the development host (Windows 11, Python 3.12.10). Nothing is estimated.

## Evidence

| Item | Result |
|---|---|
| Automated tests (default suite) | **97 passed, 0 failed** (4 live tests deselected by default) |
| Live tests (`GR_LIVE_TESTS=1 pytest -m live tests/live`) | **4 passed, 0 failed** (MH portal, Odisha STSC, Odisha Agri, MP Social Justice) |
| Line coverage (core, crawlers, services, apps) | **86%** (2161 statements, 311 missed). Mostly uncovered: RQ worker entry points, MinIO backend, real OCR subprocess, eGazette search loop |
| Official PDFs downloaded and validated | **28** (each re-checked from storage: `%PDF-` signature, `%%EOF`, PyMuPDF parse, SHA-256 match) |
| Unique binaries | 28 |
| Dead-lettered downloads in live runs | 0 |
| Alembic | `upgrade head` applied on SQLite; `alembic check` reports no drift; offline SQL rendered for PostgreSQL (8 tables) |

### Validated PDFs by source

| Source | Discovered | Downloaded and validated |
|---|---|---|
| `mh_gr_portal` (live portal, 2 listing pages) | 20 | 8 |
| `mh_gr_portal` via `mh_orgpedia_backfill` (2018 GRs) | 5 | 5 |
| `mp_socialjustice_circulars` (1 page) | 10 | 5 |
| `od_stsc_resolutions` (1 page) | 20 | 5 |
| `od_agri_resolutions` (1 page) | 17 | 5 |
| `od_agri_notifications` (Scrapy run, 1 page, downloads off) | 20 | 0 |

Download limits were deliberately small. These counts show the pipeline works; they are **not** coverage figures. No coverage percentage is claimed, because there is no verified denominator of all published documents.

### Text extraction outcome on the 28 archived PDFs

| State | `done` | `needs_ocr` | Reason |
|---|---|---|---|
| Maharashtra | 0 | 13 | Unicode text layer has Devanagari glyph-ordering errors (`glyph_order_errors`) |
| Madhya Pradesh | 0 | 5 | Private-Use-Area or control chars (`broken_unicode_mapping`), or no text layer |
| Odisha | 6 | 4 | 4 scans with no text layer |

`needs_ocr` documents keep their raw text-layer text and diagnostics. They are re-processed with `grctl extract-pending` on a host with OCR installed (the Docker image has it).

## Completed features
- **Source audit** of all provided portals (`docs/source-audit.md`), with statuses in `configs/sources.yaml`.
- **Adapters** on a common interface (`discover_documents`, `extract_listing_metadata`, `resolve_document_url`, `fetch_document`, `normalize_metadata`, `persist_discovery_state`):
  - Maharashtra GR portal (ASP.NET postback pagination, no CAPTCHA path)
  - Maharashtra Orgpedia seed backfill (official downloads only)
  - Odisha Drupal Views (generic across departments, columns mapped by field class)
  - Odisha eGazette (CSRF POST search; row parser not verified)
  - MP Social Justice (session-bound AJAX offset pagination)
- **Polite HTTP client:** domain allowlist, SSRF guard checked on every redirect hop, robots.txt, per-host rate limit, exponential backoff with jitter, Retry-After, no retry on 401/403, conditional GET, streamed downloads with size cap, content-type and `%PDF` checks, detection of truncated downloads.
- **Scrapy runtime** (`apps/crawler/scrapy_spider.py`) reusing the same parsers, with AutoThrottle, `ROBOTSTXT_OBEY`, OffsiteMiddleware allowlist and optional scrapy-playwright. Verified live (20 items).
- **Persistence:** PostgreSQL/SQLite models for sources, documents, document_versions, crawl_runs, crawl_checkpoints, document_pages, document_relationships and dead_letters; Alembic migration `0001`.
- **Storage:** content-addressed, write-once originals (`originals/<sha>.pdf`) and derived OCR PDFs kept separately (`derived/ocr/…`). Backends: MinIO and local filesystem.
- **Dedup:** identity is (source, canonical_id); SHA-256 binary duplicates are linked; titles are never used.
- **Versioning:** `discovered`, `initial_download`, `binary_changed`, `metadata_changed`, `manual_import`.
- **Incremental mode:** stops after consecutive fully-known pages, optional conditional-GET recheck. **Backfill mode:** resumable checkpoints after every listing page.
- **Extraction:** PyMuPDF per page with pypdf fallback. Deterministic quality gates: no text layer, legacy-font gibberish, Private-Use-Area/control chars, Indic glyph-order errors. Each page gets a confidence score. OCRmyPDF/Tesseract (mar/hin/ori/eng) runs only on failing pages.
- **API:** all 13 required endpoints, bearer-token auth on crawl admin endpoints, filters, pagination, page-text search with snippets.
- **Ops:** CLI (`grctl`), RQ worker, APScheduler per-source cron, Prometheus metrics, structured JSON logs, dead-letter table, manual-import workflow, Docker Compose (Postgres, Redis, MinIO, migrate, API, worker, scheduler, optional Prometheus/Grafana).

## Tested features (automated)
Static HTML parsing (MH, Odisha), dynamic AJAX listing (MP), ASP.NET postback form building, pagination (all three patterns), URL resolution and canonicalisation, valid PDF download, invalid / truncated / mislabelled / oversized PDF rejection, interrupted download, duplicate PDF detection, metadata normalisation (dates, Indic digits, departments, types, languages), Marathi/Hindi/Odia Unicode preservation (normaliser, DB → API, and PDF text round-trip using the Nirmala font), OCR fallback (OCR binary mocked), OCR-unavailable path, checkpoint recovery after an interrupted backfill, retries (503, transport errors), 429 with Retry-After, 403 without retry and dead-lettered, robots.txt allow/deny/403, redirect SSRF rejection, DB transaction failure rollback, provenance fields, incremental new-document detection with early stop, binary and metadata version changes, admin API authentication, manual import, CLI, scheduler job registration, Scrapy spider parsing.

## Not tested
- **Real OCR.** Tesseract/OCRmyPDF are not installed on the development host. The OCR code path is only tested with a mocked OCR binary. Not yet run end to end: OCR inside the Docker image and `scripts/ocr_benchmark.py`.
- **Docker Compose stack, PostgreSQL, MinIO, Redis/RQ.** Docker is not installed on the development host. The PostgreSQL DDL was rendered but never applied to a live server. The MinIO backend and the RQ queue/worker have never run.
- **Playwright path.** No audited source needs a browser, so scrapy-playwright is wired but not exercised.
- **eGazette result-row parsing.** No result rows were observable.
- **Large-scale backfill behaviour** (thousands of documents, rate tuning).

## Source-specific blockers
- **Maharashtra:** the portal's historical search requires a CAPTCHA, so it is not automated. Backfill instead uses the Orgpedia identifier list (only `mahagri` configured) plus manual import.
- **Odisha Cabinet:** expired TLS certificate.
- **Odisha eGazette:** only 2024 is selectable and searches returned no rows.
- **Odisha CTZ / MP eService:** citizen-service portals with no document repository.
- **Bhumi Abhilekh:** connection timeout.
- **MP:** no central repository. Only one departmental adapter exists so far.

## Remaining work (priority order)
1. Run the Docker stack: `alembic upgrade head` on PostgreSQL, the MinIO backend, RQ workers.
2. Install OCR (Docker image) and run `grctl extract-pending` on the 22 `needs_ocr` documents.
3. Build a manually transcribed OCR benchmark set for Marathi/Hindi. Their text layers are unreliable, so `ocr_benchmark.py` has no ground truth for them.
4. Add the remaining Orgpedia department repos to `mh_orgpedia_backfill.options.repos` after checking each repo name.
5. Audit more Odisha departments (Drupal template; config-only once verified) and more MP departments (one adapter each).
6. Write the `mh_dte_grs` WordPress adapter.
7. Add a PostgreSQL trigram/GIN index migration for search once the corpus grows.
8. Add Grafana dashboards for the exported metrics.
