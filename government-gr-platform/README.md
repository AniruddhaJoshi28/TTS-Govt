# Government GR Platform

A self-hosted, open-source system that finds, downloads, validates, archives and indexes official government resolutions, circulars, orders and notifications from **Maharashtra, Madhya Pradesh and Odisha**.

It uses no paid APIs and no LLMs. Discovery, deduplication and metadata extraction are all deterministic.

- Source findings and status of every portal: [`docs/source-audit.md`](docs/source-audit.md)
- What works, what has been tested, and what is still open: [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md)

## Architecture

```
configs/sources.yaml ──► adapters (crawlers/<state>/) ──► PoliteClient (allowlist · robots · rate limit · retries)
                                  │                              │
                    DiscoveredDocument (pydantic)          streamed PDF download (size cap, %PDF check)
                                  │                              │
          services/discovery/pipeline.py ── upsert (source, canonical_id) ── validate → SHA-256 → object store (write-once)
                                  │                                                            │
            crawl_runs · crawl_checkpoints · document_versions · dead_letters        services/pdf_extraction (PyMuPDF/pypdf)
                                  │                                                            │ quality gates
                         PostgreSQL (SQLite for dev)                                services/ocr (OCRmyPDF + Tesseract mar/hin/ori)
                                  │                                                            │
                     apps/api (FastAPI)  ·  apps/scheduler (APScheduler)  ·  apps/downloader (RQ worker)  ·  Scrapy runtime
```

| Layer | Implementation |
|---|---|
| Crawling | Per-portal adapters on a shared interface; HTTPX `PoliteClient`; Scrapy spider reusing the same parsers |
| Storage | PostgreSQL + Alembic; MinIO (or local filesystem) for content-addressed originals |
| Queue / schedule | Redis + RQ (inline fallback when no Redis); APScheduler cron per source |
| Processing | PyMuPDF → pypdf fallback → OCRmyPDF/Tesseract only on pages that fail quality checks |
| API | FastAPI, bearer-token auth on admin endpoints, Prometheus `/metrics` |

## Quick start (local, no Docker)

```bash
cd government-gr-platform
python -m venv .venv
.venv/Scripts/activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps

python -m apps.crawler.cli init-db
python -m apps.crawler.cli sources
python -m apps.crawler.cli crawl od_stsc_resolutions --max-pages 1 --download-limit 5
python -m apps.crawler.cli crawl mh_gr_portal --max-pages 2 --download-limit 10
python -m apps.crawler.cli crawl mp_socialjustice_circulars --max-pages 1
python -m apps.crawler.cli backfill mh_orgpedia_backfill --options '{"limit_per_repo": 20}'
python -m apps.crawler.cli stats

uvicorn apps.api.main:app --port 8000   # http://localhost:8000/docs
```

Defaults: SQLite at `data/gr_platform.sqlite3`, PDFs under `data/objects/`, jobs run inline.

## Full stack (Docker Compose)

```bash
cp .env.example .env     # set GR_ADMIN_API_TOKEN, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD
docker compose up -d --build              # postgres, redis, minio, migrate, api, worker, scheduler
docker compose --profile monitoring up -d # + prometheus, grafana
docker compose run --rm worker python -m apps.crawler.cli crawl od_stsc_resolutions --max-pages 1
docker compose run --rm worker python -m apps.crawler.cli extract-pending   # OCR the needs_ocr documents
```

The image installs Tesseract with Marathi, Hindi, Odia and English language packs, plus OCRmyPDF.

## CLI (`grctl` or `python -m apps.crawler.cli`)

| Command | Purpose |
|---|---|
| `init-db` | Create tables (dev) and sync `sources.yaml` into the DB |
| `sources` | List sources with audit status |
| `crawl <source> [--max-pages N] [--download-limit N] [--recheck]` | Incremental crawl (stops at known documents; `--recheck` re-validates existing files with conditional GET) |
| `backfill <source> [--restart]` | Resumable historical crawl driven by checkpoints |
| `crawl-active` | Incremental crawl of every active source |
| `download-pending` / `extract-pending` | Retry downloads or text extraction / OCR |
| `import-manual manifest.csv --operator NAME` | Import PDFs that an operator downloaded by hand (CAPTCHA/TLS-blocked sources) |
| `stats` | Archive counts |

Scrapy runtime: `scrapy runspider apps/crawler/scrapy_spider.py -a source=od_stsc_resolutions -a max_pages=2`

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | DB check plus document count |
| GET | `/sources`, `/sources/{id}` | Includes audit status and access policy |
| GET | `/documents` | Filters: `state, department, document_type, language, document_number, source_id, date_from, date_to`; `limit/offset` |
| GET | `/documents/search?q=` | Searches title, number and page text; returns snippet and page number |
| GET | `/documents/{id}` | Metadata, provenance (listing URL, original URL, ETag, redirects), version history |
| GET | `/documents/{id}/download` | Original PDF (`X-Content-SHA256` header) |
| GET | `/documents/{id}/pages` | Per-page text, extraction method, confidence, diagnostics |
| GET | `/crawl/runs`, `/crawl/runs/{id}` | Run counts and errors |
| POST | `/crawl/start`, `/crawl/backfill` | **Bearer token required** (`GR_ADMIN_API_TOKEN`) |
| GET | `/metrics` | Prometheus |

## Crawling policy
- Only hosts on each source's `allowed_hosts` list are contacted. Every redirect hop is checked, and private or loopback targets are rejected.
- robots.txt is honoured when published. A 4xx or HTML soft-404 counts as "no rules".
- At most one request per host every 2 s by default. Retries use exponential backoff with jitter and respect Retry-After.
- **401/403 are never retried or worked around. CAPTCHAs are never solved or bypassed.** There is no identity or proxy rotation.
- Original PDFs are never modified. OCR output is stored separately as a derived artifact.

## Adding a source
1. Audit the portal (robots.txt, listing structure, pagination, PDF URLs, access restrictions) and record the findings in `docs/source-audit.md`.
2. If it matches an existing pattern (for example, the Odisha Drupal template), add a `sources.yaml` entry. Otherwise, write an adapter under `crawlers/<state>/` and register it in `crawlers/base/registry.py`.
3. Save the listing HTML to `tests/fixtures/html/` and add parser tests.
4. Mark it `VERIFIED_WORKING` only after a real PDF has downloaded and passed validation.

## Tests

```bash
pytest                                          # unit + integration (mocked HTTP, fixtures from real pages)
pytest --cov=core --cov=crawlers --cov=services --cov=apps
GR_LIVE_TESTS=1 pytest -m live tests/live       # opt-in, low-volume checks against real portals
```

## Data provenance and licensing
- Documents are official public records downloaded from government servers. Every record keeps its listing URL, original URL, final URL after redirects, HTTP validators and download time.
- The Maharashtra historical backfill uses Orgpedia's MIT-licensed identifier lists (github.com/orgpedia) as a seed. No Orgpedia text or PDF is stored as authoritative.
- No translations are produced. If translations are added later, they must be stored as derived artifacts linked to the original.
