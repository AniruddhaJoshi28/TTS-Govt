"""apps/speech_service HTTP API with stand-in engines (real models need a GPU)."""

from fastapi.testclient import TestClient

from apps.speech_service import main as svc
from services.stt.service import Transcript
from services.tts.service import AudioQualityError, SpeechResult


def client(monkeypatch, tts=None, stt=None):
    monkeypatch.setattr(svc.engines, "load", lambda: None)
    monkeypatch.setattr(svc.engines, "tts", tts)
    monkeypatch.setattr(svc.engines, "stt", stt)
    monkeypatch.setattr(svc.engines, "tts_error", None if tts else "TTS_ENGINE not set")
    monkeypatch.setattr(svc.engines, "stt_error", None if stt else "STT_ENGINE not set")
    return TestClient(svc.app)


def test_health_reports_each_engine(monkeypatch):
    with client(monkeypatch, tts=object()) as c:
        h = c.get("/health").json()
    assert h["tts"]["status"] == "ok" and h["stt"]["status"] == "unavailable"


def test_synthesize_returns_wav_with_metadata(monkeypatch):
    import services.tts.service as tts_service
    monkeypatch.setattr(tts_service, "synthesize",
                        lambda text, lang, engine, speaker=None: SpeechResult(b"RIFFdata", 1.75, "parler", "Divya", text))
    with client(monkeypatch, tts=object()) as c:
        r = c.post("/synthesize", json={"text": "नमस्ते", "language": "hi"})
    assert r.status_code == 200 and r.content == b"RIFFdata"
    assert r.headers["x-voice"] == "Divya" and float(r.headers["x-duration"]) == 1.75


def test_quality_failure_is_422_and_missing_engine_503(monkeypatch):
    import services.tts.service as tts_service

    def bad(*a, **k):
        raise AudioQualityError("clipped")
    monkeypatch.setattr(tts_service, "synthesize", bad)
    with client(monkeypatch, tts=object()) as c:
        assert c.post("/synthesize", json={"text": "x", "language": "mr"}).status_code == 422
    with client(monkeypatch) as c:
        assert c.post("/synthesize", json={"text": "x", "language": "mr"}).status_code == 503


def test_transcribe(monkeypatch):
    import services.stt.service as stt_service
    monkeypatch.setattr(stt_service, "transcribe", lambda data, lang, engine: Transcript("नमस्कार", lang, 1.1, "conformer"))
    with client(monkeypatch, stt=object()) as c:
        j = c.post("/transcribe?language=mr", content=b"audio").json()
    assert j == {"text": "नमस्कार", "language": "mr", "duration_s": 1.1, "model": "conformer"}
