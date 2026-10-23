# Services and workflows

## One command

```bash
.venvs/app/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 9007
```

On Linux, the app supervises two separate model services. The web app serves straight away while they load. `bash scripts/gpu/run_all.sh --serve` does the same and also prints a health report.

| Service | Process | Launcher | Port file | Log |
|---|---|---|---|---|
| SLM | vLLM (`.venvs/vllm`) | `scripts/gpu/start_slm.sh` | `logs/vllm.port` | `logs/vllm.log` |
| Speech (TTS + STT) | `apps/speech_service` (`.venvs/app`) | `scripts/gpu/start_speech.sh` | `logs/speech.port` | `logs/speech.log` |

Ports, GPUs and the model are chosen at start-up, not configured by hand:

- **Ports:** if a port is taken (shared server), the next free one is used and recorded in the port file.
- **SLM placement:** `env.sh` puts the SLM on the GPU with the most free memory and sizes the model to fit.
- **Speech placement:** speech goes on the next GPU.
- **Model id:** the app reads it from the running vLLM (`/v1/models`).

Model services keep running when the web app restarts, so `uvicorn --reload` takes seconds instead of minutes. A watchdog restarts a service that stops responding. Stop everything with `bash scripts/gpu/stop_all.sh`.

Set `SERVICE_SUPERVISOR=off` to manage the services yourself; the app then uses `LLM_BASE_URL`.

## Ingestion workflow (DAG)

```
full:  crawl ─▶ import ─▶ reload ─┬▶ index      Qdrant, one collection per state and language
                                  └▶ summarise  agent farm: SUMMARY_WORKERS parallel SLM workers
warm:  index, summarise
```

| Agent | Does | Skips when |
|---|---|---|
| crawl | Runs the crawler on every active source in `government-gr-platform/configs/sources.yaml` | the crawler is not present |
| import | Imports new PDFs into the corpus; OCRs pages with broken text | — |
| reload | Reloads the corpus and keyword index | — |
| index | Embeds new or changed passages into `GOVT_<STATE>_<lang>` | `QDRANT_URL` is unset |
| summarise | Pre-generates each GR's summary so a click is a cache hit | the SLM is not ready |

**When it runs:**

- **On start-up:** "warm" runs once the SLM is ready (`WARM_ON_START`).
- **On a schedule:** "full" runs every `PIPELINE_INTERVAL_MINUTES`.
- **On demand:** from **System → Crawl now** in the UI, or with `POST /api/v1/pipeline/run?workflow=full|warm`.

**Robustness:**

- Failed agents are retried.
- An agent's dependents are skipped, with the reason, when it fails.
- Only one workflow runs at a time.
- Runs are kept in `data/pipeline/runs.jsonl`.

## Qdrant layout

- **Collection names:** `GOVT_MH_mr`, `GOVT_MH_en`, `GOVT_MP_hi`, `GOVT_OD_or`, `GOVT_OD_en`, and so on (prefix from `QDRANT_COLLECTION_PREFIX`).
- **Language assignment:** each passage goes to the collection of its own language, detected from its script. So a Marathi GR's English annexure is stored in `GOVT_MH_en`.
- **Search:** the question is embedded once (cached) and every language collection of the state is queried in parallel. The results are combined with keyword search by reciprocal-rank fusion.
- **Old collections:** the earlier per-state collections (`GOVT_MH`, `GOVT_MP`, `GOVT_OD`) are no longer used. Delete them from the Qdrant dashboard once the new ones are filled.

## Status

- **UI:** the **System** button opens a live view of services, document counts, the workflow DAG and run history.
- **API:** `GET /api/v1/system` returns the same data as JSON, and `GET /api/v1/health` gives a per-service health check.
