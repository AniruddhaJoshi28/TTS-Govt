# TTS-Govt — Government GR Assistant

Government GR summariser and regional-language voice assistant for Maharashtra, Madhya Pradesh and Odisha. Users find an official resolution, read a plain-language summary grounded in the source, ask questions by voice in Marathi, Hindi or Odia, and open the cited passage to verify the answer.

The full programme (scope, architecture, workstreams, 24-week roadmap, acceptance gates) is in [docs/implementation-plan.md](docs/implementation-plan.md).

## Current status — foundation (weeks 1–2)

| Area | State |
| --- | --- |
| Repository layout (plan §6) | In place |
| Shared response envelope (plan §5) | [schemas/api/envelope.py](schemas/api/envelope.py) |
| API gateway | `/api/v1/health` works; every other planned endpoint returns `501 not_implemented` |
| Source registry | [services/source_registry/sources.yaml](services/source_registry/sources.yaml): all entries unverified, none crawlable |
| Crawler (weeks 3–5) | [services/crawler/](services/crawler/): bounded retries, per-host rate limit, same-host enforcement, truncation detection. Site adapters pending source verification |
| Versioned store | [services/document_ingestion/store.py](services/document_ingestion/store.py): content-addressed originals, dedup, revision history, retry queue, crawl runs (SQLite until weeks 6–8) |
| PDF extraction | [services/pdf_ocr/extract.py](services/pdf_ocr/extract.py): page-level text, scanned pages flagged `needs_ocr`; OCR engine not yet integrated |
| Metadata | [services/metadata_extraction/normalise.py](services/metadata_extraction/normalise.py): Devanagari/Odia digits, day-first dates, rupee amounts with source spans |
| Grounded Q&A (weeks 9–11, partial) | BM25 retrieval, pluggable SLM, citation and date/amount validation, bounded retries. No SLM connected yet |
| Edge-case matrix (plan §4) | [data/test_manifests/edge_cases.yaml](data/test_manifests/edge_cases.yaml): EC-01–03, 07–09, 16 implemented; 16 pending |
| Demo videos | [docs/demo_scripts/](docs/demo_scripts/): draft Marathi, Hindi, Odia scripts; no video produced yet |

## Development

```sh
pip install -e ".[dev]"
python -m pytest            # unit tests + edge-case matrix (pending cases show as skipped)
uvicorn apps.api.main:app --reload
```

## Ground rules

These come from the plan's non-negotiable failure rules:

- Never fabricate an official document, source link, GR number or citation. Unknown means `null` or an explicit uncertainty, not a guess.
- Never present synthetic (TTS) speech as a human recording.
- Never commit government data dumps, credentials, private recordings or model artefacts. `.gitignore` blocks the common formats.
- A source may only be crawled once it is `verified` and `terms_reviewed` in the registry.
