"""API gateway implementing the /api/v1 contracts from plan §5, plus the web UI.

Configuration (environment variables):
    CORPUS_DIR     built corpus (default data/corpus)
    LLM_BASE_URL   OpenAI-compatible model server, e.g. http://gpu-host:8000/v1
    LLM_MODEL      model name served there (default Qwen/Qwen3-8B)
    TTS_ENGINE     "parler" to load Indic Parler-TTS, or "clone:<voice_id>" (consent required)
    STT_ENGINE     "indicconformer" to load IndicConformer
    API_KEY        if set, required as X-API-Key on every POST

Nothing here fabricates output: when a model is not configured or fails, the
endpoint returns an explicit error envelope.
"""

import hashlib
import json
import logging
import os
import re as _re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _log_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [
            a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a
            for a in args
        ]
        print(*safe_args, **kwargs)

from fastapi import Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from schemas.api.envelope import Envelope, ErrorDetail, Language, SourceRef, State, Uncertainty
from services.document_ingestion.converter import (
    ALLOWED_EXTENSIONS,
    ALLOWED_LABEL,
    MAX_FILE_BYTES,
    ConversionError,
    UnsupportedFormat,
    detect_language,
    detect_type,
    to_pdf,
)
from services.document_ingestion.corpus import (
    CorpusDocument,
    build_document,
    load_corpus,
    render_page_images,
    save,
)
from services.document_ingestion.manifest import DocumentEntry
from services.pdf_ocr.extract import extract_pages
from services.retrieval.bm25 import BM25Index, Passage
from services.slm_orchestrator.answer import answer
from services.slm_orchestrator.llm import LLMConfig, LLMUnavailable, OpenAICompatibleLLM
from services.slm_orchestrator.summarise import summarise

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
API_PREFIX = "/api/v1"
WEB_DIR = ROOT / "apps" / "web"
CACHE_DIR = ROOT / "data" / "cache"
FEEDBACK_FILE = ROOT / "data" / "feedback" / "feedback.jsonl"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BYTES = MAX_FILE_BYTES  # from converter

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


# -- runtime state -----------------------------------------------------------

class Runtime:
    def __init__(self):
        self.corpus_dir = Path(os.environ.get("CORPUS_DIR", ROOT / "data" / "corpus"))
        self.corpus: dict[str, CorpusDocument] = {}
        self.indexes: dict[str, BM25Index] = {}
        cfg = LLMConfig.from_env()
        self.llm = OpenAICompatibleLLM(cfg) if cfg else None
        self.tts = None
        self.tts_error: str | None = None
        self.stt = None
        self.stt_error: str | None = None
        self.jobs: dict[str, dict] = {}
        # Finished speech by (text, language, speaker): the same answer is not synthesized
        # twice, and a "Listen" click on an already-spoken answer plays immediately.
        self.speech_cache: dict[str, dict] = {}
        self.pool = ThreadPoolExecutor(max_workers=1)  # one GPU, one synthesis at a time
        self.lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        self.corpus = load_corpus(self.corpus_dir) if self.corpus_dir.exists() else {}
        self.indexes = {doc_id: BM25Index(doc.to_passages()) for doc_id, doc in self.corpus.items()}

    def load_speech(self) -> None:
        tts = os.environ.get("TTS_ENGINE", "")
        try:
            if tts == "parler":
                from services.tts.engines import IndicParlerTTS
                self.tts = IndicParlerTTS()
            elif tts.startswith("clone:"):
                from services.tts.engines import IndicF5Clone
                self.tts = IndicF5Clone(tts.split(":", 1)[1])
        except Exception as exc:  # report, don't crash the API
            self.tts_error = f"{type(exc).__name__}: {exc}"
        if os.environ.get("STT_ENGINE") == "indicconformer":
            try:
                from services.stt.service import IndicConformerSTT
                self.stt = IndicConformerSTT()
            except Exception as exc:
                self.stt_error = f"{type(exc).__name__}: {exc}"


rt = Runtime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    rt.load_speech()
    yield


app = FastAPI(title="Government GR Assistant API", version="0.2.0", lifespan=lifespan)


# -- plumbing ----------------------------------------------------------------

@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    try:
        request_id = str(uuid.UUID(incoming))
    except ValueError:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _error_body(request: Request, code: str, message: str, retryable: bool = False, language=Language.ENGLISH):
    return Envelope[None](request_id=request.state.request_id, language=language,
                          error=ErrorDetail(code=code, message=message, retryable=retryable)).model_dump(mode="json")


@app.exception_handler(ApiError)
async def _api_error(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content=_error_body(request, exc.code, exc.message, exc.retryable))


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) for e in exc.errors())
    return JSONResponse(status_code=422, content=_error_body(request, "invalid_request", f"Invalid fields: {fields}"))


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("API_KEY")
    if expected and x_api_key != expected:
        raise ApiError(401, "unauthorised", "A valid API key is required.")


def _doc(doc_id: str) -> CorpusDocument:
    doc = rt.corpus.get(doc_id)
    if doc is None:
        raise ApiError(404, "document_not_found", "No document with this id is in the corpus.")
    return doc


def _source(p: Passage) -> SourceRef:
    return SourceRef(document_id=p.document_id, version_id=p.version_id, url=p.url,
                     page=p.page or None, passage_id=p.passage_id)


def _require_llm():
    if rt.llm is None:
        raise ApiError(503, "model_not_configured", "The language model server is not configured (LLM_BASE_URL).")
    return rt.llm


# -- health ------------------------------------------------------------------

class DependencyStatus(BaseModel):
    name: str
    status: str  # "ok" | "unavailable" | "not_configured"
    detail: str | None = None


class Health(BaseModel):
    status: str  # "ok" | "degraded"
    dependencies: list[DependencyStatus]


def _llm_status() -> DependencyStatus:
    if rt.llm is None:
        return DependencyStatus(name="slm", status="not_configured")
    import requests
    try:
        resp = requests.get(f"{rt.llm.config.base_url}/models", timeout=5)
        served = [m.get("id") for m in resp.json().get("data", [])] if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        served = None
    if served is None:
        return DependencyStatus(name="slm", status="unavailable", detail=rt.llm.model)
    if rt.llm.model not in served:
        # The server is up but serves a different model: every request would fail with 404.
        return DependencyStatus(name="slm", status="unavailable",
                                detail=f"configured {rt.llm.model}, but the server serves {', '.join(map(str, served))}")
    return DependencyStatus(name="slm", status="ok", detail=rt.llm.model)


@app.get(f"{API_PREFIX}/health", response_model=Envelope[Health])
def health(request: Request) -> Envelope[Health]:
    from services.pdf_ocr.ocr import OcrUnavailable, available_languages, find_tesseract
    try:
        cmd = find_tesseract()
        missing = sorted({"mar", "hin", "ori", "eng"} - available_languages(cmd))
        ocr = (DependencyStatus(name="ocr", status="ok", detail=cmd) if not missing else
               DependencyStatus(name="ocr", status="unavailable",
                                detail="missing language data: " + ", ".join(missing)))
    except OcrUnavailable as exc:
        ocr = DependencyStatus(name="ocr", status="not_configured", detail=str(exc))
    deps = [
        DependencyStatus(name="corpus", status="ok" if rt.corpus else "not_configured",
                         detail=f"{len(rt.corpus)} documents"),
        ocr,
        _llm_status(),
        DependencyStatus(name="tts", status="ok" if rt.tts else ("unavailable" if rt.tts_error else "not_configured"),
                         detail=rt.tts_error),
        DependencyStatus(name="stt", status="ok" if rt.stt else ("unavailable" if rt.stt_error else "not_configured"),
                         detail=rt.stt_error),
    ]
    overall = "ok" if all(d.status == "ok" for d in deps) else "degraded"
    return Envelope[Health](request_id=request.state.request_id, language=Language.ENGLISH,
                            data=Health(status=overall, dependencies=deps))


# -- documents ---------------------------------------------------------------

class DocumentSummary(BaseModel):
    id: str
    state: State
    language: Language
    document_type: str
    issued: str
    department: str
    department_en: str
    title: str
    title_en: str
    url: str
    listing_url: str
    retrieved_at: str
    sha256: str
    pages: int
    text_origins: list[str]
    untrusted_numbers: int
    reviewed_passages: int


def _summary_of(doc: CorpusDocument) -> DocumentSummary:
    e: DocumentEntry = doc.entry
    return DocumentSummary(
        id=e.id, state=e.state, language=e.language, document_type=e.document_type, issued=e.issued.isoformat(),
        department=e.department, department_en=e.department_en, title=e.title, title_en=e.title_en,
        url=str(e.url), listing_url=str(e.listing_url), retrieved_at=doc.retrieved_at.isoformat(),
        sha256=doc.sha256, pages=len(doc.pages), text_origins=sorted({p.origin for p in doc.pages}),
        untrusted_numbers=sum(len(p.untrusted) for p in doc.pages),
        reviewed_passages=sum(1 for p in doc.passages if p["origin"] == "reviewed"),
    )


@app.get(f"{API_PREFIX}/documents", response_model=Envelope[list[DocumentSummary]])
def list_documents(request: Request, state: State | None = None, language: Language | None = None,
                   q: str | None = Query(default=None, max_length=200)):
    docs = [d for d in rt.corpus.values()
            if (state is None or d.entry.state == state) and (language is None or d.entry.language == language)]
    if q:
        hits = {h.passage.document_id for d in docs for h in rt.indexes[d.entry.id].search(q, k=3)}
        docs = [d for d in docs if d.entry.id in hits]
    return Envelope[list[DocumentSummary]](request_id=request.state.request_id, language=language or Language.ENGLISH,
                                           data=[_summary_of(d) for d in docs])


class PageOut(BaseModel):
    page: int
    origin: str
    reason: str | None
    text: str
    ocr_mean_conf: float | None
    untrusted: list[tuple[int, int]]


class PassageOut(BaseModel):
    passage_id: str
    page: int
    origin: str
    text: str
    untrusted: list[tuple[int, int]]


class DocumentDetail(BaseModel):
    document: DocumentSummary
    portal_metadata: dict[str, str]
    pages: list[PageOut]
    passages: list[PassageOut]


@app.get(f"{API_PREFIX}/documents/{{document_id}}", response_model=Envelope[DocumentDetail])
def get_document(request: Request, document_id: str):
    doc = _doc(document_id)
    detail = DocumentDetail(
        document=_summary_of(doc), portal_metadata=doc.entry.portal_metadata,
        pages=[PageOut(**p.model_dump(exclude={"corrected"})) for p in doc.pages],
        passages=[PassageOut(**{k: p[k] for k in PassageOut.model_fields}) for p in doc.passages],
    )
    return Envelope[DocumentDetail](request_id=request.state.request_id, language=doc.entry.language, data=detail)


@app.get(f"{API_PREFIX}/documents/{{document_id}}/pages/{{page}}.png")
def page_image(document_id: str, page: int):
    _doc(document_id)
    path = rt.corpus_dir / document_id / f"page-{page}.png"
    if page < 1 or not path.is_file():
        raise ApiError(404, "page_not_found", "No image for this page.")
    return FileResponse(path, media_type="image/png")


# -- summaries and Q&A -------------------------------------------------------

class ClaimOut(BaseModel):
    text: str
    citations: list[str]


class SectionOut(BaseModel):
    key: str
    status: str
    claims: list[ClaimOut]


class SummaryOut(BaseModel):
    document_id: str
    status: str
    sections: list[SectionOut]
    model: str
    generated_at: str
    removed_claims: int


class SummaryRequest(BaseModel):
    document_id: str = Field(max_length=200)
    language: Language


@app.post(f"{API_PREFIX}/summaries", response_model=Envelope[SummaryOut], dependencies=[Depends(require_key)])
def create_summary(request: Request, body: SummaryRequest, refresh: bool = False):
    doc = _doc(body.document_id)
    llm = _require_llm()
    key = hashlib.sha256(f"{doc.sha256}|{body.language.value}|{llm.model}|{len(doc.passages)}".encode()).hexdigest()[:24]
    cache = CACHE_DIR / "summaries" / f"{key}.json"
    if cache.exists() and not refresh:
        _log_print(f"📦 [CACHE HIT] Returning cached summary for doc='{doc.entry.id}' ({body.language.value})")
        return JSONResponse({**json.loads(cache.read_text(encoding="utf-8")), "request_id": request.state.request_id})

    _log_print(f"\n🚀 [API REQUEST: /summaries] Generating fresh summary for doc='{doc.entry.id}'...")
    passages = doc.to_passages()
    if not passages:
        raise ApiError(
            422,
            "document_not_searchable",
            "This document has no readable passages. Configure OCR and upload it again before generating a summary.",
        )
    try:
        result = summarise(passages, body.language, llm)
    except LLMUnavailable as exc:
        raise ApiError(503, "model_unavailable", str(exc), retryable=True) from exc
    out = SummaryOut(
        document_id=doc.entry.id, status=result.status, model=llm.model,
        generated_at=datetime.now(timezone.utc).isoformat(), removed_claims=len(result.rejected),
        sections=[SectionOut(key=s.key, status=s.status, claims=[ClaimOut(**c.model_dump()) for c in s.claims])
                  for s in result.sections],
    )
    env = Envelope[SummaryOut](
        request_id=request.state.request_id, language=body.language, data=out,
        sources=[_source(p) for p in result.sources],
        uncertainties=[Uncertainty(code="model_note", message=u) for u in result.uncertainties],
    )
    if result.status == "summarised":
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(env.model_dump_json(), encoding="utf-8")
    return env


class QaRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    language: Language
    document_id: str | None = Field(default=None, max_length=200)
    state: State | None = None


class QaOut(BaseModel):
    status: str
    claims: list[ClaimOut]
    model: str
    removed_claims: int


@app.post(f"{API_PREFIX}/qa", response_model=Envelope[QaOut], dependencies=[Depends(require_key)])
def question_answer(request: Request, body: QaRequest, refresh: bool = False):
    if body.document_id:
        doc = _doc(body.document_id)
        index = rt.indexes.get(doc.entry.id)
        scope = doc.sha256
        target_name = f"doc '{doc.entry.id}'"
    else:
        if body.state is None:
            raise ApiError(400, "state_required", "Please choose a state or a document so the right orders are searched.")
        docs = [d for d in rt.corpus.values() if d.entry.state == body.state]
        index = BM25Index([p for d in docs for p in d.to_passages()])
        scope = ",".join(sorted(d.sha256 for d in docs))
        target_name = f"state '{body.state.value}' ({len(docs)} docs)"
    llm = _require_llm()

    # The same question about the same document version gets the same answer (also what makes
    # recorded demos show exactly the answer that was checked). refresh=true asks again.
    question = " ".join(body.question.split())
    passages_n = len(index.passages)
    key = hashlib.sha256(f"{scope}|{passages_n}|{body.language.value}|{llm.model}|{question}".encode()).hexdigest()[:24]
    cache = CACHE_DIR / "answers" / f"{key}.json"
    if cache.exists() and not refresh:
        _log_print(f"📦 [CACHE HIT] Returning cached Q&A answer for {target_name} query='{question}'")
        return JSONResponse({**json.loads(cache.read_text(encoding="utf-8")), "request_id": request.state.request_id})

    _log_print(f"\n🚀 [API REQUEST: /qa] Query: \"{question}\" | Target: {target_name} | Language: {body.language.value}")
    try:
        result = answer(question, body.language, index, llm)
    except LLMUnavailable as exc:
        raise ApiError(503, "model_unavailable", str(exc), retryable=True) from exc
    env = Envelope[QaOut](
        request_id=request.state.request_id, language=body.language,
        data=QaOut(status=result.status, claims=[ClaimOut(**c.model_dump()) for c in result.claims],
                   model=llm.model, removed_claims=len(result.rejected)),
        sources=[_source(p) for p in result.sources],
        uncertainties=[Uncertainty(code="model_note", message=u) for u in result.uncertainties],
    )
    if result.status != "failed":
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(env.model_dump_json(), encoding="utf-8")
    return env


# -- speech ------------------------------------------------------------------

class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    language: Language
    speaker: str | None = Field(default=None, max_length=40)


class SynthesisJob(BaseModel):
    job_id: str
    status: str  # "queued" | "running" | "done" | "failed"
    synthetic: bool = True
    model: str | None = None
    voice: str | None = None
    duration_s: float | None = None
    error: str | None = None


def _speech_key(req: SynthesisRequest) -> str:
    return hashlib.sha256(f"{req.language.value}|{req.speaker or ''}|{' '.join(req.text.split())}".encode()).hexdigest()


def _run_synthesis(job_id: str, req: SynthesisRequest) -> None:
    from services.tts.service import AudioQualityError, synthesize
    job = rt.jobs[job_id]
    job["status"] = "running"
    _log_print(f"🔊 [TTS SYNTHESIS] Generating audio in {req.language.value} ({len(req.text):,} chars)...")
    try:
        result = synthesize(req.text, req.language.value, rt.tts, req.speaker)
    except AudioQualityError as exc:
        _log_print(f"❌ [TTS ERROR] Quality error: {exc}")
        job.update(status="failed", error=str(exc))
        return
    except Exception as exc:  # engine crash: report, never substitute other audio
        _log_print(f"❌ [TTS ERROR] Engine error: {exc}")
        job.update(status="failed", error=f"synthesis error: {type(exc).__name__}")
        return
    job.update(status="done", model=result.model, voice=result.voice, duration_s=round(result.duration_s, 2),
               wav=result.wav)
    _log_print(f"🔊 [TTS COMPLETED] {result.duration_s:.2f}s audio synthesized using voice '{result.voice}' ({result.model})")
    if len(rt.speech_cache) > 500:
        rt.speech_cache.clear()
    rt.speech_cache[_speech_key(req)] = dict(job)


@app.post(f"{API_PREFIX}/speech/synthesis", response_model=Envelope[SynthesisJob], status_code=202,
          dependencies=[Depends(require_key)])
def create_synthesis(request: Request, body: SynthesisRequest):
    if rt.tts is None:
        raise ApiError(503, "tts_unavailable", "Speech synthesis is not available. The text answer is still valid.",
                       retryable=bool(rt.tts_error))
    job_id = uuid.uuid4().hex
    cached = rt.speech_cache.get(_speech_key(body))
    if cached:
        rt.jobs[job_id] = dict(cached)
        data = SynthesisJob(job_id=job_id, **{k: v for k, v in cached.items() if k != "wav"})
        return Envelope[SynthesisJob](request_id=request.state.request_id, language=body.language, data=data)
    rt.jobs[job_id] = {"status": "queued"}
    rt.pool.submit(_run_synthesis, job_id, body)
    return Envelope[SynthesisJob](request_id=request.state.request_id, language=body.language,
                                  data=SynthesisJob(job_id=job_id, status="queued"))


@app.get(f"{API_PREFIX}/speech/synthesis/{{job_id}}", response_model=Envelope[SynthesisJob])
def synthesis_status(request: Request, job_id: str):
    job = rt.jobs.get(job_id)
    if job is None:
        raise ApiError(404, "job_not_found", "Unknown synthesis job.")
    data = SynthesisJob(job_id=job_id, **{k: v for k, v in job.items() if k != "wav"})
    return Envelope[SynthesisJob](request_id=request.state.request_id, language=Language.ENGLISH, data=data)


@app.get(f"{API_PREFIX}/speech/synthesis/{{job_id}}/audio")
def synthesis_audio(job_id: str):
    job = rt.jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise ApiError(404, "audio_not_ready", "Audio is not available for this job.")
    return Response(job["wav"], media_type="audio/wav", headers={"X-Synthetic-Speech": "true"})


class TranscriptOut(BaseModel):
    text: str
    duration_s: float
    model: str
    needs_confirmation: bool


@app.post(f"{API_PREFIX}/speech/transcriptions", response_model=Envelope[TranscriptOut],
          dependencies=[Depends(require_key)])
async def create_transcription(request: Request, language: Language):
    from services.stt.service import AudioRejected, transcribe
    if rt.stt is None:
        raise ApiError(503, "stt_unavailable", "Speech recognition is not available. Please type your question.")
    data = await request.body()
    if len(data) > MAX_AUDIO_BYTES:
        raise ApiError(413, "audio_too_large", "The recording is too large.")
    try:
        t = transcribe(data, language.value, rt.stt)
    except AudioRejected as exc:
        raise ApiError(422, "audio_rejected", str(exc)) from exc
    return Envelope[TranscriptOut](request_id=request.state.request_id, language=language,
                                   data=TranscriptOut(text=t.text, duration_s=round(t.duration_s, 2), model=t.model,
                                                      needs_confirmation=True))


# -- audio library and feedback ---------------------------------------------

@app.get(f"{API_PREFIX}/audio-assets/{{asset_id}}")
def audio_asset(asset_id: str):
    raise ApiError(404, "audio_asset_not_found",
                   "No approved human recording exists for this item yet. Recordings are added after script approval.")


class FeedbackRequest(BaseModel):
    document_id: str | None = Field(default=None, max_length=200)
    kind: str = Field(pattern="^(incorrect|unclear|helpful|pronunciation|other)$")
    comment: str = Field(default="", max_length=1000)
    language: Language


@app.post(f"{API_PREFIX}/feedback", response_model=Envelope[dict], dependencies=[Depends(require_key)])
def feedback(request: Request, body: FeedbackRequest):
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {**body.model_dump(mode="json"), "at": datetime.now(timezone.utc).isoformat(),
              "request_id": request.state.request_id}
    with rt.lock, FEEDBACK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return Envelope[dict](request_id=request.state.request_id, language=body.language, data={"received": True})


# -- document upload ---------------------------------------------------------

class UploadResult(BaseModel):
    document_id: str
    filename: str
    original_format: str
    detected_language: str
    state: str
    pages: int
    passages: int
    message: str


class FormatsOut(BaseModel):
    extensions: list[str]
    max_size_mb: int
    description: str


@app.get(f"{API_PREFIX}/upload/formats", response_model=Envelope[FormatsOut])
def upload_formats(request: Request):
    """Return the list of accepted file formats and size limits."""
    return Envelope[FormatsOut](
        request_id=request.state.request_id,
        language=Language.ENGLISH,
        data=FormatsOut(
            extensions=sorted(ALLOWED_EXTENSIONS),
            max_size_mb=int(MAX_UPLOAD_BYTES / (1024 * 1024)),
            description=ALLOWED_LABEL,
        ),
    )


@app.post(f"{API_PREFIX}/upload", response_model=Envelope[UploadResult],
          dependencies=[Depends(require_key)])
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="Document file to upload"),
    language: Language | None = Form(default=None, description="Override auto-detected language"),
    state: State | None = Form(default=None, description="State this document belongs to"),
    title: str = Form(default="", description="Document title (auto-generated if empty)"),
):
    """Upload any supported document, convert to PDF, ingest, and make it
    immediately available for summaries and Q&A."""
    # -- read and validate -----------------------------------------------
    content = await file.read()
    if not content:
        raise ApiError(400, "empty_file", "The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(
            413, "file_too_large",
            f"File is {len(content) / (1024*1024):.1f} MB; limit is "
            f"{MAX_UPLOAD_BYTES / (1024*1024):.0f} MB.",
        )

    filename = file.filename or "document"
    ext = Path(filename).suffix.lower()

    # Stable document ID from filename and content hash
    content_sha = hashlib.sha256(content).hexdigest()
    safe_name = _re.sub(r"[^a-zA-Z0-9_-]", "-", Path(filename).stem.lower())[:50]
    doc_id = f"upload-{safe_name}-{content_sha[:10]}"
    doc_title = title or Path(filename).stem.replace("_", " ").replace("-", " ").title()

    _log_print(f"\n{'='*75}")
    _log_print(f"📥 [DOCUMENT UPLOAD INGESTION PIPELINE STARTED]")
    _log_print(f"   • File: '{filename}' ({len(content):,} bytes / {len(content)/(1024*1024):.2f} MB)")
    _log_print(f"   • Title: '{doc_title}'")
    _log_print(f"   • Document ID: {doc_id}")

    # Retry legacy/failed zero-passage artifacts after OCR is installed instead
    # of falsely treating them as successfully ingested documents.
    if doc_id in rt.corpus and rt.corpus[doc_id].passages:
        existing = rt.corpus[doc_id]
        _log_print(f"ℹ️ [UPLOAD FAST-PATH] Document '{doc_id}' already ingested. Ready for immediate querying.")
        _log_print(f"{'='*75}\n")
        return Envelope[UploadResult](
            request_id=request.state.request_id,
            language=existing.entry.language,
            data=UploadResult(
                document_id=doc_id,
                filename=filename,
                original_format=detect_type(filename, content),
                detected_language=existing.entry.language.value,
                state=existing.entry.state.value,
                pages=len(existing.pages),
                passages=len(existing.passages),
                message="Document was already uploaded and is ready for questions.",
            ),
        )

    # -- convert to PDF --------------------------------------------------
    _log_print(f"  [Step 1/6] 🔄 Sniffing format & normalizing to PDF...")
    try:
        original_type = detect_type(filename, content)
        pdf_bytes = to_pdf(filename, content)
        _log_print(f"      ✓ Detected format: {original_type.upper()}")
        _log_print(f"      ✓ Normalized to PDF: {len(pdf_bytes):,} bytes")
    except UnsupportedFormat as exc:
        _log_print(f"  ❌ Unsupported format: {exc}")
        _log_print(f"{'='*75}\n")
        raise ApiError(
            415, "unsupported_format",
            f"{exc}  Accepted formats: {ALLOWED_LABEL}.",
        ) from exc
    except ConversionError as exc:
        _log_print(f"  ❌ Conversion error: {exc}")
        _log_print(f"{'='*75}\n")
        raise ApiError(422, "conversion_failed", str(exc)) from exc

    # -- extract text and detect language --------------------------------
    _log_print(f"  [Step 2/6] 📄 Extracting pages & inspecting embedded text...")
    from services.pdf_ocr.extract import InvalidPdf, extract_pages
    try:
        pages = extract_pages(pdf_bytes)
        embedded_pages = sum(1 for p in pages if p.method == "embedded")
        _log_print(f"      ✓ Total pages: {len(pages)} (Embedded text: {embedded_pages}, Scanned/OCR fallback: {len(pages) - embedded_pages})")
    except InvalidPdf as exc:
        _log_print(f"  ❌ Invalid document: {exc}")
        _log_print(f"{'='*75}\n")
        raise ApiError(422, "invalid_document", str(exc)) from exc

    _log_print(f"  [Step 3/6] 🌐 Detecting language & script...")
    all_text = "\n".join(p.text for p in pages if p.text)
    detected_lang = language.value if language else detect_language(all_text)
    # Validate the detected language is one we support.
    try:
        lang_enum = Language(detected_lang)
    except ValueError:
        lang_enum = Language.ENGLISH
        detected_lang = "en"
    _log_print(f"      ✓ Auto-detected language: '{detected_lang}' (Language Enum: {lang_enum.name})")

    # -- build corpus entry ----------------------------------------------
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    now = datetime.now(timezone.utc)
    doc_state = state or State.UPLOADED

    entry = DocumentEntry(
        id=doc_id,
        state=doc_state,
        language=lang_enum,
        document_type="uploaded",
        issued=date.today(),
        department="User Upload",
        department_en="User Upload",
        title=doc_title,
        title_en=doc_title,
        url=f"file:///{doc_id}",
        listing_url=f"file:///{doc_id}",
        fetch={"method": "upload"},
        portal_metadata={},
    )

    # Scanned pages require OCR. Do not save a zero-passage artifact and claim
    # that it is ready for questions.
    scanned_pages = len(pages) - embedded_pages
    ocr = None
    try:
        from services.pdf_ocr.ocr import OCR_LANGS, OcrUnavailable, TesseractOcr, require_languages
        if scanned_pages:
            cmd = require_languages(OCR_LANGS[lang_enum.value])
            ocr = TesseractOcr(cmd=cmd)
    except OcrUnavailable as exc:
        _log_print(f"  OCR unavailable for {scanned_pages} scanned page(s): {exc}")
        _log_print(f"{'='*75}\n")
        raise ApiError(
            503, "ocr_unavailable",
            f"This document has {scanned_pages} scanned page(s), but OCR is not ready: {exc}",
            retryable=True,
        ) from exc

    _log_print(f"  [Step 4/6] ✂️ Chunking into citable passages with zero-hallucination span tracking...")
    try:
        corpus_doc = build_document(entry, pdf_bytes, sha, now, ocr)
    except OcrUnavailable as exc:
        raise ApiError(503, "ocr_failed", f"OCR could not read this document: {exc}", retryable=True) from exc
    _log_print(f"      ✓ Created {len(corpus_doc.passages)} citable passage(s)")

    if not corpus_doc.passages:
        raise ApiError(
            422, "document_has_no_text",
            "No readable text was found. Try a clearer scan or select its language before uploading.",
        )

    # Save to disk.
    _log_print(f"  [Step 5/6] 💾 Persisting document artifacts & rendering page preview thumbnails...")
    save(corpus_doc, rt.corpus_dir)

    # Render page images for the source panel.
    try:
        render_page_images(pdf_bytes, rt.corpus_dir / doc_id)
        _log_print(f"      ✓ Rendered {len(corpus_doc.pages)} page preview thumbnail(s)")
    except Exception as exc:
        logger.warning("Could not render page images for %s: %s", doc_id, exc)

    # Hot-add to runtime (no restart needed).
    _log_print(f"  [Step 6/6] ⚡ Live indexing passages into in-memory BM25 index...")
    rt.corpus[doc_id] = corpus_doc
    rt.indexes[doc_id] = BM25Index(corpus_doc.to_passages())
    _log_print(f"      ✓ Document '{doc_id}' is LIVE in corpus ({len(rt.corpus)} total documents active)")
    _log_print(f"      ✓ Ready for: Q&A queries, 9-point structured summaries, TTS audio synthesis")
    _log_print(f"✅ [INGESTION PIPELINE COMPLETE] Document ID: {doc_id}")
    _log_print(f"{'='*75}\n")

    logger.info(
        "Uploaded %s: %s → %d pages, %d passages, language=%s",
        doc_id, filename, len(corpus_doc.pages), len(corpus_doc.passages), detected_lang,
    )

    return Envelope[UploadResult](
        request_id=request.state.request_id,
        language=lang_enum,
        data=UploadResult(
            document_id=doc_id,
            filename=filename,
            original_format=original_type,
            detected_language=detected_lang,
            state=doc_state.value,
            pages=len(corpus_doc.pages),
            passages=len(corpus_doc.passages),
            message="Document uploaded and ready for summaries and questions.",
        ),
    )


@app.post(f"{API_PREFIX}/reload", response_model=Envelope[dict], dependencies=[Depends(require_key)])
def reload_corpus(request: Request):
    """Re-scan the corpus directory and rebuild all indexes."""
    rt.reload()
    return Envelope[dict](
        request_id=request.state.request_id,
        language=Language.ENGLISH,
        data={"documents": len(rt.corpus), "reloaded": True},
    )


# -- web UI ------------------------------------------------------------------

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
