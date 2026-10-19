# Government GR Assistant — Model Inventory and End-to-End Architecture

## 1. Model installation status

Audit date: **19 October 2026**. Audit scope: the current Windows workstation and this repository.

**None of the models required by this application are fully downloaded on this machine.**

- There is no project `.env`, `.venvs`, `models`, or `logs` directory.
- No `vllm`, Uvicorn, or application Python process is running.
- `C:\Users\AniruddhaJoshi\.cache\huggingface\hub\models--Qwen--Qwen3-8B` exists, but contains only metadata (`refs` and `.no_exist`). It has no `snapshots` or weight blobs, so it is **not a usable downloaded model**.
- No Hugging Face cache directory exists for the application's AI4Bharat TTS or STT models.

This only proves the state of the current workstation. A separate Linux/GPU host could have the models, but no configured `LLM_BASE_URL` or running service in this workspace currently identifies such a host.

## 2. Models used by the code

| Purpose | Model/repository ID | Required by default? | How the application uses it | Normal storage after download |
|---|---|---:|---|---|
| Grounded summary and Q&A | `Qwen/Qwen3-8B` | Yes for generated answers | vLLM serves an OpenAI-compatible HTTP API; the application calls `/v1/chat/completions` | Linux: `~/.cache/huggingface/hub/models--Qwen--Qwen3-8B/`; Windows equivalent: `%USERPROFILE%\.cache\huggingface\hub\models--Qwen--Qwen3-8B\` |
| Lower-memory LLM fallback | `Qwen/Qwen3-4B` | Selected automatically when GPU memory is below the 8B threshold | Same vLLM interface | Corresponding Hugging Face cache directory |
| Speech-to-text | `ai4bharat/indic-conformer-600m-multilingual` | Yes when `STT_ENGINE=indicconformer` | Loaded in the API process by Transformers `AutoModel.from_pretrained`; converts Marathi, Hindi, or Odia audio to text | Hugging Face cache: `models--ai4bharat--indic-conformer-600m-multilingual/` |
| Text-to-speech | `ai4bharat/indic-parler-tts` | Yes when `TTS_ENGINE=parler` (default GPU script setting) | Loaded in the API process by Parler-TTS/Transformers; generates synthetic speech | Hugging Face cache: `models--ai4bharat--indic-parler-tts/` plus any referenced tokenizer/text-encoder cache |
| Consent-controlled voice cloning | `ai4bharat/IndicF5` | Optional alternative when `TTS_ENGINE=clone:<voice_id>` | Loaded only after a signed local consent record and reference audio are found | Hugging Face cache: `models--ai4bharat--IndicF5/`; voice data under `data/voices/<voice_id>/` |
| Scanned-document OCR | Tesseract `tessdata_best`: `mar`, `hin`, `ori`, `eng` | Needed for scanned pages | Local Tesseract executable and language-data files; this is OCR, not an LLM | Project GPU setup places language data in `.tools/tessdata/` |

The repository also mentions `sarvamai/sarvam-m` as an **evaluation candidate**, not the production default. Llama 3.2 is mentioned as a swappable/benchmarkable example. Neither is selected by the normal runtime configuration.

The unrelated models already present in the workstation's global Hugging Face cache (Whisper, Llama, embedding models, and others) are not referenced by this application's runtime and do not make this project model-ready.

## 3. How models are obtained and started

The models are intentionally not committed to Git. On the intended Linux/GPU host:

1. `scripts/gpu/setup.sh` creates separate application and vLLM environments.
2. `scripts/gpu/download_models.sh` calls Hugging Face `snapshot_download` for the configured LLM, Indic Parler-TTS, and IndicConformer. Gated models require `HF_TOKEN` and accepted repository terms.
3. `scripts/gpu/env.sh` examines free GPU memory. It normally selects Qwen3-8B, but selects Qwen3-4B when memory is insufficient; it also assigns the application speech models to a GPU.
4. `scripts/gpu/run_all.sh` starts vLLM on port `8001`, waits for `/v1/models`, and then starts the FastAPI application on port `8000`.
5. The API never loads the Qwen weights itself. It sends prompts over HTTP to the configured OpenAI-compatible model server. STT and TTS weights, however, are loaded directly inside the API process.

If `LLM_BASE_URL` is absent, summary and Q&A return `model_not_configured`. If the model server cannot be reached, they return `model_unavailable`. Typed document browsing and deterministic BM25 retrieval remain local. If STT or TTS is unavailable, the UI falls back to typed input or written output respectively.

## 4. Complete architecture

```mermaid
flowchart TB
    U([Citizen / operator])

    subgraph Client[Browser — apps/web]
      UI[Multilingual UI<br/>Marathi · Hindi · Odia · English]
      FILE[Document upload<br/>PDF/DOCX/ODT/RTF/TXT/images]
      TYPE[Typed question]
      MIC[Microphone recording]
      LISTEN[Listen request]
      SRC[Source/citation and page viewer]
      PLAYER[WAV player<br/>synthetic-speech label]
    end

    U --> UI
    UI --> FILE
    UI --> TYPE
    UI --> MIC
    UI --> LISTEN

    subgraph Gateway[FastAPI gateway — apps/api/main.py]
      REQ[Request ID · API-key check<br/>schema and size validation]
      HEALTH[Dependency health checks]
      ROUTES[Documents · upload · summary · Q&A<br/>STT · TTS · feedback]
      ERR[Explicit error envelope<br/>no fabricated fallback]
    end

    FILE -->|POST /api/v1/upload| REQ
    TYPE -->|POST /api/v1/qa| REQ
    MIC -->|POST /api/v1/speech/transcriptions| REQ
    LISTEN -->|POST /api/v1/speech/synthesis| REQ
    REQ --> ROUTES
    HEALTH -. checks .-> ROUTES
    ROUTES -. failure .-> ERR
    ERR --> UI

    subgraph Ingest[Document ingestion pipeline]
      SNIFF[Validate bytes and sniff real format]
      CONVERT[Normalize supported input to PDF]
      EXTRACT[Extract embedded page text]
      SCAN{Usable embedded text?}
      RENDER[Render scanned page]
      OCR[Tesseract OCR<br/>mar · hin · ori · eng]
      LANG[Detect/override language and state]
      CRITICAL[Mark uncertain critical spans<br/>dates · amounts · numbers]
      CHUNK[Create page-bound citable passages<br/>with stable passage IDs]
      SAVE[Persist normalized PDF, corpus JSON<br/>and page-preview images]
      HOT[Hot-add document to runtime]
    end

    ROUTES -->|upload bytes| SNIFF
    SNIFF --> CONVERT --> EXTRACT --> SCAN
    SCAN -->|yes| LANG
    SCAN -->|no| RENDER --> OCR --> LANG
    LANG --> CRITICAL --> CHUNK --> SAVE --> HOT

    subgraph Storage[Private local data plane]
      CORPUS[(data/corpus<br/>documents · pages · passages)]
      BM25[(In-memory BM25 indexes<br/>words + Indic character trigrams)]
      CACHE[(data/cache<br/>version/model/question-keyed JSON)]
      PAGES[(Page previews and original source metadata)]
      FEEDBACK[(data/feedback/feedback.jsonl)]
      VOICES[(data/voices<br/>consent + reference audio)]
      SPEECHCACHE[(In-memory TTS job/result cache)]
    end

    SAVE --> CORPUS
    SAVE --> PAGES
    HOT --> BM25
    CORPUS -->|API startup/reload| BM25
    ROUTES --> FEEDBACK

    subgraph STT[Spoken-input path]
      AUDIOCHECK[Decode with ffmpeg to<br/>16 kHz mono PCM]
      VALIDATEA[Reject undecodable, silent,<br/>&lt;0.5 s or &gt;60 s audio]
      CONFORMER[IndicConformer 600M<br/>local inference]
      CONFIRM[Show transcript for mandatory<br/>user confirmation/correction]
    end

    ROUTES -->|recording + selected language| AUDIOCHECK
    AUDIOCHECK --> VALIDATEA --> CONFORMER --> CONFIRM
    CONFIRM -->|confirmed text becomes normal question| TYPE

    subgraph QA[Grounded Q&A path]
      SCOPE[Resolve selected document<br/>or all documents in selected state]
      SEARCH[BM25 top-8 passage retrieval]
      EVIDENCE{Any matching evidence?}
      PROMPT[Build injection-resistant prompt<br/>question + delimited passages + language]
      QLLMCALL[OpenAI-compatible JSON request<br/>temperature 0.1 · thinking disabled]
      QPARSE[Parse required JSON shape<br/>up to 3 constrained attempts]
      FACT[Deterministic factual validation]
      CLAIMS[Keep only cited claims whose<br/>dates, amounts and numbers occur<br/>in trusted cited passages]
    end

    ROUTES -->|question, language, scope| SCOPE --> SEARCH
    BM25 --> SEARCH --> EVIDENCE
    EVIDENCE -->|no| NOEVID[insufficient_evidence response]
    EVIDENCE -->|yes| PROMPT --> QLLMCALL --> QPARSE --> FACT --> CLAIMS

    subgraph Summary[Structured summary path]
      ALLPASS[Use document's citable passages]
      SPROMPT[Request nine structured sections<br/>as cited JSON claims]
      SLLMCALL[OpenAI-compatible JSON request]
      SPARSE[Parse nine-section JSON<br/>up to 3 constrained attempts]
      SVALIDATE[Validate every section/claim<br/>against cited trusted passages]
      SRESULT[Return supported sections;<br/>mark missing/rejected material]
    end

    ROUTES -->|document + output language| ALLPASS --> SPROMPT --> SLLMCALL --> SPARSE --> SVALIDATE --> SRESULT

    subgraph LLMHost[Local/private GPU model service]
      VLLM[vLLM OpenAI-compatible server<br/>/v1/models · /v1/chat/completions]
      QWEN[Qwen3-8B default<br/>Qwen3-4B low-memory fallback]
      HFCACHE[(Hugging Face model cache)]
      HFCACHE --> QWEN --> VLLM
    end

    QLLMCALL -->|HTTP via LLM_BASE_URL| VLLM
    SLLMCALL -->|HTTP via LLM_BASE_URL| VLLM
    VLLM -->|Q&A JSON| QPARSE
    VLLM -->|summary JSON| SPARSE

    subgraph TTS[Written-answer to speech path]
      TKEY[Hash language + speaker + text]
      TCACHE{Previously synthesized?}
      JOB[Async single-GPU job<br/>queued → running]
      NORMAL[Remove citations; normalize symbols,<br/>numbers and pronunciation lexicons]
      SPLIT[Split text into sentence-sized chunks]
      ENGINE{Configured engine}
      PARLER[Indic Parler-TTS<br/>named regional speaker]
      F5[IndicF5 voice clone<br/>consent required before load]
      QUALITY[Regenerate implausible takes;<br/>polish, pauses, duration/truncation checks]
      WAV[WAV response + model/voice/duration<br/>X-Synthetic-Speech: true]
    end

    CLAIMS --> RESPONSE
    SRESULT --> RESPONSE
    NOEVID --> RESPONSE
    RESPONSE[API envelope<br/>request ID · language · status · claims<br/>sources · uncertainties · model] --> CACHE
    CACHE -->|repeat request| RESPONSE
    RESPONSE --> UI
    RESPONSE --> SRC

    ROUTES --> TKEY --> TCACHE
    SPEECHCACHE --> TCACHE
    TCACHE -->|hit| WAV
    TCACHE -->|miss| JOB --> NORMAL --> SPLIT --> ENGINE
    ENGINE -->|parler| PARLER --> QUALITY
    ENGINE -->|clone:voice_id| VOICES --> F5 --> QUALITY
    QUALITY -->|job done; failure stays explicit| WAV --> SPEECHCACHE
    WAV --> PLAYER --> U

    HFCACHE --> CONFORMER
    HFCACHE --> PARLER
    HFCACHE --> F5
```

## 5. Output guarantees and boundaries

- A generated answer is returned only after retrieval, JSON-shape validation, citation validation, and deterministic checking of numeric/date/amount values.
- OCR spans marked unreliable cannot be used as trusted evidence for those critical values.
- The answer envelope carries the request ID, selected language, sources, uncertainty notices, status, and actual configured model name.
- Repeated summaries and questions are cached using the document content/version, language, model, and normalized question, preventing accidental reuse across changed documents or models.
- TTS is asynchronous and cached separately. It never substitutes unrelated audio on failure and always identifies generated audio as synthetic.
- The present implementation uses local BM25 retrieval. Multilingual embeddings and reranking are described as future work in the implementation plan and are not in the current runtime path.
