import json
import time
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient

from apps.api import main
from services.document_ingestion.corpus import build_document, save
from services.slm_orchestrator.llm import LLMUnavailable
from services.tts.engines import Audio
from tests.helpers import make_pdf
from tests.unit.test_corpus import FakeOcr, entry

client = TestClient(main.app)
DOC_ID = "doc"
OCR_TEXT = "अकुशल श्रमिक की दैनिक दर 484 रुपये है।\n\nये दरें न्यूनतम वेतन अधिनियम के अंतर्गत हैं।"


class FakeLLM:
    model = "fake-model"

    def __init__(self, reply=None, exc=None):
        self.reply, self.exc = reply, exc

    def __call__(self, prompt):
        if self.exc:
            raise self.exc
        return self.reply


class FakeTTS:
    def synthesize(self, chunks, lang, speaker=None):
        sr = 16000
        n = int(sum(len(c) for c in chunks) * 0.08 * sr)
        return Audio((0.3 * np.sin(np.arange(n) / 10)).astype(np.float32), sr, "fake-tts", "Divya")


@pytest.fixture(autouse=True)
def corpus(tmp_path, monkeypatch):
    doc = build_document(entry(id=DOC_ID), make_pdf(None), "ab" * 32, datetime(2026, 10, 17, tzinfo=timezone.utc),
                         FakeOcr(OCR_TEXT))
    save(doc, tmp_path)
    monkeypatch.setattr(main.rt, "corpus_dir", tmp_path)
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(main, "FEEDBACK_FILE", tmp_path / "feedback.jsonl")
    monkeypatch.setattr(main.rt, "llm", None)
    monkeypatch.setattr(main.rt, "tts", None)
    monkeypatch.delenv("API_KEY", raising=False)
    main.rt.reload()
    yield


def test_health_reports_each_dependency():
    body = client.get("/api/v1/health").json()
    deps = {d["name"]: d["status"] for d in body["data"]["dependencies"]}
    assert deps["corpus"] == "ok" and deps["slm"] == "not_configured"
    assert body["data"]["status"] == "degraded"


def test_request_id_is_echoed_when_valid():
    rid = str(uuid.uuid4())
    resp = client.get("/api/v1/health", headers={"X-Request-ID": rid})
    assert resp.headers["X-Request-ID"] == rid and resp.json()["request_id"] == rid


def test_invalid_request_id_is_replaced():
    uuid.UUID(client.get("/api/v1/health", headers={"X-Request-ID": "<script>"}).headers["X-Request-ID"])


def test_list_and_get_document():
    docs = client.get("/api/v1/documents", params={"state": "MP"}).json()["data"]
    assert [d["id"] for d in docs] == [DOC_ID] and docs[0]["text_origins"] == ["ocr"]
    assert client.get("/api/v1/documents", params={"state": "OD"}).json()["data"] == []
    detail = client.get(f"/api/v1/documents/{DOC_ID}").json()["data"]
    assert detail["pages"][0]["text"].startswith("अकुशल") and detail["passages"][0]["passage_id"] == "doc:meta"


def test_unknown_document_is_404_envelope():
    body = client.get("/api/v1/documents/nope").json()
    assert body["error"]["code"] == "document_not_found" and body["data"] is None


def test_summary_without_model_fails_explicitly():
    resp = client.post("/api/v1/summaries", json={"document_id": DOC_ID, "language": "hi"})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "model_not_configured"


def test_summary_with_model_is_validated_and_cached(monkeypatch):
    reply = json.dumps({"sections": {
        "benefits": [{"text": "अकुशल श्रमिक को 484 रुपये प्रतिदिन", "citations": [f"{DOC_ID}:p1:1"]}],
        "dates": [{"text": "लागू तिथि 01.04.2027", "citations": [f"{DOC_ID}:p1:1"]}],
    }}, ensure_ascii=False)
    monkeypatch.setattr(main.rt, "llm", FakeLLM(reply))
    body = client.post("/api/v1/summaries", json={"document_id": DOC_ID, "language": "hi"}).json()
    sections = {s["key"]: s for s in body["data"]["sections"]}
    assert sections["benefits"]["status"] == "stated"
    assert sections["dates"]["status"] == "not_stated"  # invented date removed
    assert body["data"]["removed_claims"] == 1 and body["sources"][0]["page"] == 1
    monkeypatch.setattr(main.rt, "llm", FakeLLM(exc=AssertionError("cache should be used")))
    main.rt.llm.model = "fake-model"
    again = client.post("/api/v1/summaries", json={"document_id": DOC_ID, "language": "hi"}).json()
    assert again["data"]["sections"] == body["data"]["sections"]


def test_model_outage_is_retryable_error(monkeypatch):
    monkeypatch.setattr(main.rt, "llm", FakeLLM(exc=LLMUnavailable("down")))
    resp = client.post("/api/v1/qa", json={"question": "अकुशल दर?", "language": "hi", "document_id": DOC_ID})
    assert resp.status_code == 503 and resp.json()["error"]["retryable"] is True


def test_qa_requires_state_or_document(monkeypatch):
    monkeypatch.setattr(main.rt, "llm", FakeLLM("{}"))
    resp = client.post("/api/v1/qa", json={"question": "दर क्या है?", "language": "hi"})
    assert resp.json()["error"]["code"] == "state_required"


def test_qa_answer_with_citation(monkeypatch):
    reply = json.dumps({"claims": [{"text": "अकुशल श्रमिक की दैनिक दर 484 रुपये है।", "citations": [f"{DOC_ID}:p1:1"]}]},
                       ensure_ascii=False)
    monkeypatch.setattr(main.rt, "llm", FakeLLM(reply))
    body = client.post("/api/v1/qa", json={"question": "अकुशल श्रमिक की दैनिक दर", "language": "hi", "state": "MP"}).json()
    assert body["data"]["status"] == "answered" and body["sources"][0]["passage_id"] == f"{DOC_ID}:p1:1"


def test_tts_unavailable_is_explicit():
    resp = client.post("/api/v1/speech/synthesis", json={"text": "नमस्ते", "language": "hi"})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "tts_unavailable"


def test_tts_job_produces_labelled_synthetic_audio(monkeypatch):
    monkeypatch.setattr(main.rt, "tts", FakeTTS())
    job = client.post("/api/v1/speech/synthesis", json={"text": "अकुशल श्रमिक की दैनिक दर", "language": "hi"}).json()
    job_id = job["data"]["job_id"]
    for _ in range(50):
        status = client.get(f"/api/v1/speech/synthesis/{job_id}").json()["data"]
        if status["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert status["status"] == "done" and status["synthetic"] is True
    audio = client.get(f"/api/v1/speech/synthesis/{job_id}/audio")
    assert audio.headers["content-type"] == "audio/wav" and audio.headers["X-Synthetic-Speech"] == "true"


def test_stt_unavailable_is_explicit():
    resp = client.post("/api/v1/speech/transcriptions", params={"language": "hi"}, content=b"x")
    assert resp.json()["error"]["code"] == "stt_unavailable"


def test_no_fake_human_recordings():
    assert client.get("/api/v1/audio-assets/anything").json()["error"]["code"] == "audio_asset_not_found"


def test_feedback_and_validation(tmp_path):
    ok = client.post("/api/v1/feedback", json={"kind": "unclear", "language": "mr", "comment": "x"})
    assert ok.json()["data"] == {"received": True}
    bad = client.post("/api/v1/feedback", json={"kind": "spam", "language": "mr"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"


def test_api_key_enforced_on_post(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    assert client.post("/api/v1/feedback", json={"kind": "other", "language": "hi"}).status_code == 401
    ok = client.post("/api/v1/feedback", json={"kind": "other", "language": "hi"}, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200


def test_answers_are_cached_per_question_and_refreshable(monkeypatch):
    reply = json.dumps({"claims": [{"text": "अकुशल श्रमिक की दैनिक दर 484 रुपये है।", "citations": [f"{DOC_ID}:p1:1"]}]},
                       ensure_ascii=False)
    monkeypatch.setattr(main.rt, "llm", FakeLLM(reply))
    q = {"question": "अकुशल श्रमिक की दैनिक दर", "language": "hi", "document_id": DOC_ID}
    first = client.post("/api/v1/qa", json=q).json()
    monkeypatch.setattr(main.rt, "llm", FakeLLM(exc=AssertionError("cache should be used")))
    main.rt.llm.model = "fake-model"
    spaced = client.post("/api/v1/qa", json={**q, "question": "  अकुशल  श्रमिक की दैनिक दर "}).json()
    assert spaced["data"] == first["data"]
    monkeypatch.setattr(main.rt, "llm", FakeLLM(json.dumps({"claims": []})))
    refreshed = client.post("/api/v1/qa?refresh=true", json=q).json()
    assert refreshed["data"]["status"] == "insufficient_evidence"


@pytest.mark.parametrize("served,status", [(["fake-model"], "ok"), (["Qwen/Qwen3-8B"], "unavailable")])
def test_health_checks_the_served_model(monkeypatch, served, status):
    # Seen on the GPU server: vLLM served Qwen3-8B while the app asked for Qwen3-4B -> HTTP 404.
    import requests

    from services.slm_orchestrator.llm import LLMConfig, OpenAICompatibleLLM

    llm = OpenAICompatibleLLM(LLMConfig(base_url="http://gpu:8001/v1", model="fake-model"))
    monkeypatch.setattr(main.rt, "llm", llm)
    resp = type("R", (), {"status_code": 200, "json": lambda self: {"data": [{"id": m} for m in served]}})()
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp)
    slm = next(d for d in client.get("/api/v1/health").json()["data"]["dependencies"] if d["name"] == "slm")
    assert slm["status"] == status
    if status != "ok":
        assert "Qwen/Qwen3-8B" in slm["detail"]
