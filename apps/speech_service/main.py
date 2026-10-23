"""Speech service: TTS (Indic Parler-TTS or a consented voice clone) and STT (IndicConformer)
in their own process, on their own GPU, behind a small HTTP API.

Started and supervised by the main app (apps/api/supervisor.py) through scripts/gpu/start_speech.sh,
so model loading never blocks or crashes the web app, and the app can be restarted (uvicorn --reload)
without reloading multi-GB speech models.

    POST /synthesize   {"text", "language", "speaker"} -> audio/wav (+ X-Duration, X-Model, X-Voice)
    POST /transcribe?language=mr   <audio bytes>     -> {"text", "language", "duration_s", "model"}
    GET  /health                                       -> per-engine status
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class _Engines:
    def __init__(self):
        self.tts = None
        self.tts_error: str | None = None
        self.stt = None
        self.stt_error: str | None = None
        self.lock = threading.Lock()  # one GPU: one synthesis at a time

    def load(self) -> None:
        tts = os.environ.get("TTS_ENGINE", "")
        try:
            if tts == "parler":
                from services.tts.engines import IndicParlerTTS
                self.tts = IndicParlerTTS()
            elif tts.startswith("clone:"):
                from services.tts.engines import IndicF5Clone
                self.tts = IndicF5Clone(tts.split(":", 1)[1])
            elif tts:
                self.tts_error = f"unknown TTS_ENGINE {tts!r}"
        except Exception as exc:  # report, never crash the service
            self.tts_error = f"{type(exc).__name__}: {exc}"
        if os.environ.get("STT_ENGINE") == "indicconformer":
            try:
                from services.stt.service import IndicConformerSTT
                self.stt = IndicConformerSTT()
            except Exception as exc:
                self.stt_error = f"{type(exc).__name__}: {exc}"


engines = _Engines()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engines.load()
    yield


app = FastAPI(title="GR Assistant speech service", version="1.0", lifespan=lifespan)


def _status(engine, error: str | None, configured: str) -> dict:
    if engine is not None:
        return {"status": "ok", "model": getattr(engine, "model_id", type(engine).__name__)}
    return {"status": "unavailable" if error else "not_configured", "detail": error or f"{configured} not set"}


@app.get("/health")
def health() -> dict:
    return {"tts": _status(engines.tts, engines.tts_error, "TTS_ENGINE"),
            "stt": _status(engines.stt, engines.stt_error, "STT_ENGINE")}


class SynthesisIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    language: str = Field(min_length=2, max_length=5)
    speaker: str | None = Field(default=None, max_length=40)


@app.post("/synthesize")
def synthesize(body: SynthesisIn) -> Response:
    from services.tts.service import AudioQualityError, synthesize as run

    if engines.tts is None:
        raise HTTPException(503, detail=engines.tts_error or "TTS_ENGINE not set")
    try:
        with engines.lock:
            result = run(body.text, body.language, engines.tts, body.speaker)
    except AudioQualityError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return Response(result.wav, media_type="audio/wav", headers={
        "X-Duration": f"{result.duration_s:.3f}", "X-Model": result.model, "X-Voice": result.voice})


@app.post("/transcribe")
async def transcribe(request: Request, language: str) -> dict:
    from services.stt.service import AudioRejected, transcribe as run

    if engines.stt is None:
        raise HTTPException(503, detail=engines.stt_error or "STT_ENGINE not set")
    try:
        t = run(await request.body(), language, engines.stt)
    except AudioRejected as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"text": t.text, "language": t.language, "duration_s": t.duration_s, "model": t.model}
