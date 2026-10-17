# Implementation Plan: Government GR Summariser + Regional-Language Voice Assistant

Maharashtra, Madhya Pradesh and Odisha · 24-week implementation plan

This is a product-development programme, not only an SLM project: a reliable government-document intelligence platform, multilingual speech, secure deployment, thorough edge-case handling, and client demonstration videos in natural regional languages.

The product must feel like a knowledgeable local-language government assistance service, not a robotic chatbot. Explanations must be clear, respectful, easy to understand, and grounded in actual government documents.

Human-recorded audio is used for approved fixed content and natural-sounding TTS for dynamic summaries. Dynamically generated TTS is never claimed to be human-recorded speech.

## 1. Scope

| Module | Purpose |
| --- | --- |
| 1. Government data collection | Discover, scrape and index authorised public GRs, circulars, notifications, scheme guidelines and amendments from official sources across all three states. |
| 2. Document intelligence and SLM summarisation | Turn long documents into simple explanations, eligibility rules, benefits, deadlines, required documents and application procedures, with evidence from the original GR. |
| 3. Regional-language STT | Spoken questions in Marathi, Hindi and Odia, with English-source support, accents, background noise and code-switching. |
| 4. Human-recorded audio and TTS | Approved human recordings for critical fixed content; TTS for dynamic summaries, with pronunciation controls and audio-quality evaluation. |
| 5. Governance, security and auditability | Protect documents and logs, version documents, keep evidence trails, enforce API boundaries, and make failures visible. |
| 6. Client demonstration videos | Explanatory demo videos in Marathi, Hindi and Odia with human narration, natural pacing, accurate pronunciation, readable captions and real product footage. |

**Definition of success:** a user can find an official resolution, understand it, ask a question in their own language, hear an intelligible explanation, and open the source to verify the answer. The client can see that workflow end to end, including what happens when the system does not know an answer.

## 2. Architecture

```
A. Official sources      MH GR portal · MP department portals · Odisha e-Gazette and departments
B. Ingestion             discovery · crawl · download · dedup · change detection · retry queue
C. Document processing   PDF parsing · OCR · tables · script ID · quality checks · version relationships
D. Private repository    immutable PDFs · PostgreSQL metadata · BM25 · multilingual vectors · audit records
E. SLM + retrieval       intent → search → rerank → evidence extraction → summary → factual validation
   ├─ Text interface     summary, Q&A, source links, corrections
   └─ Speech interface   STT → same grounded answer → recorded audio or TTS
```

Every stage has a defined input, output, validation rule and failure path.

**Deployment boundary:** originals, indexes, metadata and audit trail stay in private infrastructure. Only the minimum necessary content goes to an external model or speech service, and only once that service is approved for the data. Document search and cached content must have a fully internal fallback; no single speech or LLM provider is a hard dependency.

## 3. Workstreams

### A — Scraping and data engineering

Tasks: source registry per state/department; site-specific crawlers (permitted HTTP, HTML parsing, pagination, PDF download); browser automation only where necessary and permitted; store original file + URL + retrieval timestamp + HTTP metadata + checksum; extract identifiers, dates, department, subject, language, document type; detect duplicates and revisions; incremental scheduler and retry queue; provenance for every field and status for every crawl.

Edge cases: downtime, timeouts, proxy failures, rate limiting; redirecting/expiring/restructured URLs; duplicate PDFs under different URLs; PDFs replaced without a filename change; scanned PDFs with no text; password-protected, corrupt or partial files; stale or misleading links; missing or inconsistent dates/metadata; multilingual documents; amendments on a separate website; withdrawn, cancelled or superseded orders; public documents with restrictions on automated reuse.

**Required:** a failed crawl is recorded and retried; it never silently erases the last successfully ingested document.

### B — OCR and document intelligence

Pipeline: detect extractable text → extract text and layout directly where possible → render scanned pages and apply script-appropriate OCR → recover paragraphs, headings, tables, page numbers, sections → identify language(s) → validate dates, GR numbers, amounts, tables → compare low-confidence/critical fields with the source image → save text with page-level provenance.

Special handling: similar-looking Devanagari characters (Marathi/Hindi); Odia characters and combining marks; ₹, Indian digit grouping, percentages, decimals; multi-page tables; footnotes, annexures, stamps, signatures; header/footer contamination; text as images or unusual encodings; mixed-script names, acronyms and English terminology.

Do not translate a badly recognised OCR result and assume translation repaired it. Correct or flag low-quality extraction first.

### C — RAG and SLM summarisation

Pipeline: classify request → resolve state, department, language, document → retrieve with BM25 + multilingual embeddings → rerank and apply version rules → extract facts into a structured intermediate representation → generate summary in the requested language → validate material claims against cited passages → return summary with source links, page references and uncertainty notices.

Start with a compact instruction-tuned SLM; benchmark candidates (e.g. Qwen3 4B/8B, Llama 3.2 3B) under identical conditions. Evaluate IndicTrans2 separately if translation is needed; don't assume translation preserves legal meaning without review.

Summary sections: what the GR says; who it applies to; eligibility and exclusions; benefits and financial assistance; documents required; application process and responsible department; dates and deadlines; exceptions and conditions; amendment/supersession status; source links and unresolved uncertainties.

Edge cases: no state given; similarly named schemes; query too vague for a unique GR; GR missing from corpus; latest order not the legally applicable one; contradictory documents; no deadline stated; amount only in a table/annexure; district/beneficiary-class/financial-year scope; personal eligibility requests without the needed facts; prompt injection in retrieved passages; valid-looking but unsupported JSON; wrong language or mixed scripts.

**Required:** ask a clarifying question when essential context is missing, say when evidence is insufficient, never invent a deadline or eligibility condition.

### D — Regional-language STT

Benchmark IndicConformer checkpoints and approved speech APIs on real recordings; evaluate Marathi, Hindi and Odia independently, including accents and code-switching.

Pipeline: format/duration validation → VAD and optional noise suppression → language selection or identification → recognition → confidence/ambiguity handling → correction UI for names, numbers, key terms → hand corrected text to the same retrieval/summarisation service as typed queries.

Edge cases: very short or empty audio; traffic, crowds, reverberation; clipping, low volume, overlapping speakers; Marathi with English technical words; Hindi questions about Odia/Marathi documents; Roman-script input; district/personal names and acronyms; numbers differing by one digit; unsupported or ambiguous language; low-confidence intent; sensitive personal information in audio.

If a critical number or proper noun is uncertain, request confirmation. Never auto-correct a person's name to the nearest familiar name.

### E — TTS and human-recorded audio

**Path 1, approved human recordings:** scripts for fixed guidance and critical announcements; domain-reviewer approval; native voice artists; controlled recording environment; review pronunciation, completeness, pacing, noise; store with script version, language, speaker consent, approval metadata; re-record when the script changes materially.

**Path 2, dynamic TTS:** normalise dates, amounts, abbreviations, numbers; language-specific pronunciation dictionaries; benchmark IndicF5 and approved services on identical sentences; controlled chunking and pauses; integrity and truncation checks; secondary ASR as a diagnostic only, not proof of correct pronunciation; route critical failures to human review.

Hard cases: multiple plausible pronunciations of a scheme name; acronyms read as words; ambiguous spoken dates; misread amounts; text language ≠ voice language; audio stopping mid-sentence; TTS outage; inconsistent pronunciation; output mistaken for an official human announcement.

If TTS fails, show the text and approved recorded content where applicable. Never substitute an unrelated recording to avoid an error.

## 4. Edge-case and failure-handling matrix

Tracked as automated tests in [data/test_manifests/edge_cases.yaml](../data/test_manifests/edge_cases.yaml) (EC-01 … EC-23).

| Scenario | Required behaviour |
| --- | --- |
| GR source unavailable | Show last indexed version with retrieval date; indicate freshness could not be verified. |
| Duplicate document | Deduplicate by content hash; keep provenance for each official URL. |
| Revised PDF at same URL | Detect change, preserve previous version, reprocess. |
| Amendment found | Link to the original only with supporting evidence; recalculate affected summaries. |
| Contradictory official documents | Surface both and the conflict; don't invent a resolution. |
| OCR corruption in critical field | Flag for review; withhold the unverified claim. |
| No reliable evidence | Say the available documents don't establish the answer. |
| Hallucinated citation | Reject unless it resolves to a real document and passage. |
| Malformed SLM output | Retry constrained once or twice, then safe failure. |
| Unsupported language | Ask the user to choose a supported language; never switch silently. |
| Low-confidence STT | Show transcript for correction or ask for another recording. |
| Ambiguous spoken amount/date | Confirm before a consequential answer. |
| TTS timeout | Bounded retry, then text and appropriate fallback. |
| Audio quality failure | Suppress; regenerate or route to review. |
| Network disconnection | Serve cached content where feasible, marked possibly stale. |
| Malicious PDF / prompt injection | Treat content as untrusted; isolate parsing; ignore embedded override instructions. |
| Unauthorised access | Deny, log the security event, expose no data. |
| API quota exhaustion | Rate limits, bounded retries, graceful degradation. |
| Personal information in logs | Minimise/redact; restrict access. |
| Model or prompt update | Regression tests before deploy; versioned rollback. |
| Request for guaranteed benefit | Explain documented rules and limits; never guarantee an outcome. |
| Out-of-scope action | Explain the boundary; point to the official channel if known. |
| Demo contains test data | Label synthetic scenarios; never present invented information as official. |

### Non-negotiable failure rules

1. Never fabricate an official document, source link, GR number or citation.
2. Never silently alter an eligibility condition, date or financial amount.
3. Never treat the newest document automatically as the controlling legal document.
4. Never represent an unverified summary as an official government determination.
5. Never let an external API failure silently produce incomplete or unrelated audio.
6. Never present a synthetic voice as a human recording.
7. Never expose sensitive data in logs, demo recordings or screenshots.

## 5. API contracts (proposed)

| Service | Endpoint | Responsibility |
| --- | --- | --- |
| Document search | `GET /api/v1/documents` | Search by state, department, language, date, keywords |
| Document details | `GET /api/v1/documents/{id}` | Metadata and source references |
| Summary | `POST /api/v1/summaries` | Grounded summary in the requested language |
| Question answering | `POST /api/v1/qa` | Answer using retrieved evidence |
| STT | `POST /api/v1/speech/transcriptions` | Transcribe uploaded audio |
| TTS | `POST /api/v1/speech/synthesis` | Audio for approved dynamic text |
| Audio library | `GET /api/v1/audio-assets/{id}` | Approved human-recorded audio |
| Feedback | `POST /api/v1/feedback` | Corrections and quality feedback |
| Health | `GET /api/v1/health` | Service and dependency availability |

Every response includes a request ID, selected language, source document identifiers, version information, confidence/uncertainty signals where meaningful, and error details that expose no secrets (see [schemas/api/envelope.py](../schemas/api/envelope.py)). Asynchronous TTS returns a job ID and status. Use request-size limits, authentication, bounded retries and idempotency for repeatable operations.

## 6. Repository structure

`apps/` (api, web, admin) · `services/` (source_registry, crawler, document_ingestion, pdf_ocr, metadata_extraction, version_resolution, retrieval, slm_orchestrator, factual_validation, stt, tts, audio_library, audit) · `schemas/` · `evaluation/` · `data/` (fixtures, test_manifests) · `infrastructure/` · `docs/` · `tests/` (unit, integration, end_to_end, security, acceptance).

No government data dumps, credentials, private recordings or large model artefacts in the repository.

## 7. 24-week roadmap

| Weeks | Phase | Key outputs |
| --- | --- | --- |
| 1–2 | Requirements and source discovery | Departmental scope and official sources; security, privacy, human-voice requirements; acceptance tests and architecture |
| 3–5 | Scraping and document processing | Incremental crawlers and registry; PDF extraction, OCR, metadata; original-file preservation and revision detection |
| 6–8 | Private knowledge repository | PostgreSQL + object storage; BM25 + multilingual vectors; lineage and version relationships |
| 9–11 | SLM and grounded summarisation | SLM benchmarks; structured extraction and evidence validation; evaluation in all three languages |
| 12–14 | STT and TTS engineering | Speech-model benchmarks; lexicons and normalisation; human recordings and TTS evaluation |
| 15–17 | Application integration | Multilingual text and voice UI; citations, corrections, playback; failure handling, permissions, audit |
| 18–20 | Evaluation and security hardening | Regression, edge-case, load tests; native-speaker and domain review; critical fixes |
| 21–22 | Demo production | Three native-language scripts; human narration and real footage; pronunciation, caption, claim review |
| 23–24 | UAT and pilot | Client acceptance; demo assets and deployment docs; pilot-readiness decision |

### Acceptance gates

1. **Data readiness:** provenance, extraction quality and version handling work.
2. **Intelligence readiness:** material summary claims are evidence-backed; critical facts pass validation.
3. **Speech readiness:** native speakers approve pronunciation and intelligibility against a documented protocol.
4. **Integration readiness:** text and voice behave consistently, including error and fallback paths.
5. **Client readiness:** system, security review, demo assets and acceptance docs approved.

A failed gate means remediation in the schedule, not a milestone declared complete on a happy-path demo.

## 8–10. Demo videos

Deliverables: Marathi explainer (Maharashtra), Hindi explainer (Madhya Pradesh), Odia explainer (Odisha), each ~2–3 min; combined product demo for leadership and technical stakeholders, ~4–6 min.

Standard: real native-language narrator; scripts written natively, not translated from English copy; calm conversational pace; no hype, robotic cadence or jargon; real application footage, readable captions, restrained music; second native-speaker review; product TTS clearly distinguishable from the human narrator.

Common structure: 0:00 human intro → 0:15 show the official GR (title, department, date, URL) → 0:40 summary with eligibility, benefits, documents, deadlines → 1:10 spoken question, recognised text, sourced answer → 1:35 dynamic TTS vs approved human clip, clearly labelled → 2:00 open the citation and show uncertainty handling → 2:20 human close.

Avoid claims like "understands every dialect", "100% accurate" or "guarantees eligibility".

Production workflow: select a real GR → verify every displayed fact → write three native scripts → record narration → capture real footage → edit and localise → native-speaker QA → client approval and archive.

Formats: 1080p 16:9 MP4; 30–45 s preview; SRT/VTT captions; editable script in the regional script; WAV master + compressed audio; evidence pack (source URLs, document IDs, validation record, reviewer sign-off). Unimplemented features are labelled as proposed or omitted, never simulated.

## 11. Testing and quality dashboard

Layers: unit, integration, regression, factuality, multilingual, speech (WER/CER, named entities, intelligibility, truncation), security, performance, UAT, demo tests.

Dashboard: freshness, crawl failures, OCR confidence, retrieval quality, factual error rate, STT accuracy, TTS quality, API failures and latency, broken down by state and language. No single aggregate score; Marathi, Hindi and Odia each pass their own gates.

## 12. Definition of done

- **Data:** source registry and crawler; versioned repository; OCR and metadata validation; amendment/supersession tracking.
- **Intelligence:** grounded summaries and citations; eligibility/benefit/deadline extraction; multilingual Q&A with uncertainty handling; automated factuality and regression tests.
- **Speech:** STT evaluation in all three languages; human-recorded critical audio library; dynamic TTS with pronunciation controls; native-speaker audio acceptance.
- **Product and security:** multilingual interface; private storage and approved API boundary; access control, audit trail, monitoring; failure handling and operational docs.
- **Client delivery:** Marathi, Hindi and Odia explainers; combined demo with approved captions.

Pilot-ready only when the document, factuality, security and speech gates pass and the demos are reviewed and approved.

## 13. Execution priorities

Five parallel workstreams: data engineering; AI/ML; speech engineering; application and infrastructure; language and client delivery. One shared, verified knowledge and validation layer sits behind both typed and spoken interactions, so text and voice cannot give inconsistent answers.
