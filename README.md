# TTS-Govt: Government GR Assistant

A government GR summariser and regional-language voice assistant for Maharashtra, Madhya Pradesh and Odisha. Users can:

- find an official order;
- read a plain-language summary grounded in the source;
- ask questions in Marathi, Hindi or Odia, typed or spoken;
- open the cited page of the original to verify every statement.

The full programme is in [docs/implementation-plan.md](docs/implementation-plan.md). To run it on a GPU server and record the demo videos, see [docs/operations/gpu-server.md](docs/operations/gpu-server.md).

## Quick start on a GPU server

```bash
git clone https://github.com/AniruddhaJoshi28/TTS-Govt.git && cd TTS-Govt
git checkout feature/foundation-and-ingestion
bash scripts/gpu/setup.sh     # installs Python, OCR, vLLM, TTS, model weights; runs tests
bash scripts/gpu/run_all.sh   # starts everything and records the 3 demo videos into output/demo/
```

Details, human checks before client delivery, and troubleshooting: [docs/operations/gpu-server.md](docs/operations/gpu-server.md).

## Status

| Area | State |
| --- | --- |
| Real documents | One recent official document per state ([data/demo/documents.yaml](data/demo/documents.yaml)), fetched from the official portals |
| Ingestion | Versioned, content-addressed store; dedup; revision history; retry queue ([services/document_ingestion/](services/document_ingestion/)) |
| Text extraction | Detects legacy-font corruption in embedded text (found in all sampled MH GRs) and scanned pages, and routes both to Tesseract OCR (`mar`/`hin`/`ori`+`eng`) with word confidences |
| Number safety | OCR-suspect numbers (confusable digits, impossible dates, low confidence) are masked from evidence. Human review files can sign corrected values ([data/review/](data/review/)) |
| Retrieval | BM25 with Indic-aware tokens and character trigrams; vector index pending (weeks 6–8) |
| Summaries and Q&A | Structured sections; every claim cited; every number must appear in verified source text; bounded retries |
| Model | Any OpenAI-compatible server. Default `Qwen/Qwen3-8B` on vLLM; comparison script in [evaluation/summarisation/](evaluation/summarisation/) |
| Speech | Indic Parler-TTS, IndicF5 voice cloning (consent-gated) and IndicConformer STT adapters. Audio integrity checks; all synthetic audio labelled |
| Web UI | [apps/web/](apps/web/): Marathi, Hindi, Odia, English; citations open the source page image; voice input always confirmed |
| Demo videos | Automated recording pipeline ([scripts/demo/](scripts/demo/)), with scripts in [docs/demo_scripts/scenes.yaml](docs/demo_scripts/scenes.yaml). Runs on the GPU server |
| Edge cases (plan §4) | 12 of 23 have automated tests ([data/test_manifests/edge_cases.yaml](data/test_manifests/edge_cases.yaml)) |

## Local development (no GPU)

```sh
pip install -e ".[dev]"
python -m pytest
python scripts/build_corpus.py --download   # needs Tesseract with mar/hin/ori
uvicorn apps.api.main:app --reload           # http://localhost:8000
```

Without a model server, summaries and Q&A return an explicit "not configured" error. Nothing is simulated.

## Ground rules

These come from the plan's non-negotiable rules:

- Never fabricate an official document, source link, GR number, citation, date or amount. Unknown means `null` or an explicit uncertainty.
- Never present synthetic speech as a human recording. Every generated voice is labelled.
- Never commit government data dumps, credentials, voice recordings or model artefacts.
- A source may only be crawled once it is `verified` and `terms_reviewed` in the registry.
