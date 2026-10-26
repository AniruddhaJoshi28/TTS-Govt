"""Workflow engine (DAG), agent farm, pipeline and model-service clients."""

import threading
import time

import pytest

from services.agents.dag import Node, Skip, run_dag, validate
from services.agents.farm import run_farm


def test_dag_runs_in_dependency_order_and_in_parallel():
    order, lock = [], threading.Lock()
    started = {}

    def agent(name, delay=0.0):
        def run(ctx):
            started[name] = time.monotonic()
            time.sleep(delay)
            with lock:
                order.append(name)
            ctx[name] = True
            return name
        return run

    nodes = [Node("crawl", agent("crawl")), Node("import", agent("import"), ("crawl",)),
             Node("index", agent("index", 0.3), ("import",)), Node("summarise", agent("summarise", 0.3), ("import",))]
    run = run_dag("full", nodes)
    assert run.status == "succeeded"
    assert order[:2] == ["crawl", "import"] and set(order[2:]) == {"index", "summarise"}
    assert abs(started["index"] - started["summarise"]) < 0.2  # independent branches ran together


def test_failed_node_is_retried_then_dependents_skipped():
    attempts = {"n": 0}

    def flaky(ctx):
        attempts["n"] += 1
        raise ConnectionError("portal down")

    run = run_dag("full", [Node("crawl", flaky, retries=2, retry_delay_s=0), Node("import", lambda c: 1, ("crawl",)),
                           Node("other", lambda c: "ok")], sleep=lambda s: None)
    nodes = run.nodes
    assert attempts["n"] == 3 and nodes["crawl"].status == "failed" and "portal down" in nodes["crawl"].error
    assert nodes["import"].status == "skipped" and "crawl" in nodes["import"].result
    assert nodes["other"].status == "succeeded" and run.status == "partial"


def test_skip_is_not_a_failure():
    def no_qdrant(ctx):
        raise Skip("Qdrant not configured")

    run = run_dag("warm", [Node("index", no_qdrant), Node("summarise", lambda c: {"done": 3})])
    assert run.nodes["index"].status == "skipped" and run.status == "succeeded"


def test_dag_validation():
    with pytest.raises(ValueError, match="cycle"):
        validate([Node("a", lambda c: 1, ("b",)), Node("b", lambda c: 1, ("a",))])
    with pytest.raises(ValueError, match="unknown"):
        validate([Node("a", lambda c: 1, ("missing",))])


def test_progress_updates_are_reported():
    seen = []
    run_dag("x", [Node("a", lambda c: 1)], on_update=lambda r: seen.append(r.nodes["a"].status))
    assert seen[0] == "pending" and "running" in seen and seen[-1] == "succeeded"


def test_farm_isolates_failures_and_parallelises():
    def work(job):
        if job == 3:
            raise RuntimeError("bad pdf")
        time.sleep(0.2)
        return "generated"

    t0 = time.monotonic()
    report = run_farm(range(8), work, workers=4)
    assert time.monotonic() - t0 < 1.2  # 7 x 0.2 s sequential would be 1.4 s
    assert report.done == 7 and report.failed == 1 and "bad pdf" in report.errors[0]


def test_farm_stops_early():
    report = run_farm(range(20), lambda j: "generated", workers=1, should_stop=lambda: True)
    assert report.skipped == 20 and report.done == 0


def test_remote_speech_client(monkeypatch):
    import requests

    from apps.api.supervisor import RemoteSpeech
    from services.stt.service import AudioRejected
    from services.tts.service import AudioQualityError

    class Resp:
        def __init__(self, status, content=b"", headers=None, payload=None):
            self.status_code, self.content, self.headers, self._p = status, content, headers or {}, payload

        def json(self):
            return self._p

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(str(self.status_code))

    client = RemoteSpeech("http://speech")
    replies = iter([Resp(200, b"RIFF....", {"X-Duration": "2.5", "X-Model": "parler", "X-Voice": "Sunita"}),
                    Resp(422, payload={"detail": "clipped audio"}),
                    Resp(200, payload={"text": "नमस्कार", "language": "mr", "duration_s": 1.2, "model": "conformer"}),
                    Resp(422, payload={"detail": "too short"})])
    monkeypatch.setattr(client.session, "post", lambda *a, **k: next(replies))
    r = client.synthesize("नमस्कार", "mr")
    assert r.wav == b"RIFF...." and r.duration_s == 2.5 and r.voice == "Sunita"
    with pytest.raises(AudioQualityError):
        client.synthesize("x", "mr")
    assert client.transcribe(b"audio", "mr").text == "नमस्कार"
    with pytest.raises(AudioRejected):
        client.transcribe(b"audio", "mr")


def test_supervisor_is_off_without_launch_scripts(monkeypatch):
    from apps.api import supervisor as sup

    monkeypatch.setenv("SERVICE_SUPERVISOR", "off")
    loaded = []

    class Rt:
        def load_speech(self):
            loaded.append(True)

    s = sup.Supervisor(Rt())
    assert not s.enabled
    s.start()
    assert loaded == [True]  # falls back to in-process speech


def test_pipeline_rejects_concurrent_runs_and_records_history(tmp_path, monkeypatch):
    from apps.api import pipeline as pl

    monkeypatch.setattr(pl, "HISTORY", tmp_path / "runs.jsonl")
    gate = threading.Event()

    class Rt:
        vectors = None
        llm = None
        corpus = {}

    p = pl.Pipeline(Rt(), generate_summary=None, log=lambda m: None)
    monkeypatch.setattr(p, "agent_index", lambda ctx: gate.wait(5) or {"indexed": 0})
    first = p.start("warm")
    assert first is not None and p.running
    assert p.start("warm") is None  # busy
    gate.set()
    for _ in range(100):
        if not p.running:
            break
        time.sleep(0.05)
    snap = p.snapshot()
    assert not snap["running"] and snap["history"] and snap["history"][0]["dag"] == "warm"
    statuses = {n["name"]: n["status"] for n in snap["history"][0]["nodes"]}
    assert statuses == {"index": "succeeded", "summarise": "skipped"}  # no SLM -> skipped, not failed
    assert (tmp_path / "runs.jsonl").read_text(encoding="utf-8").strip()


def _pipeline(monkeypatch, tmp_path, sup_status, llm=object()):
    from apps.api import pipeline as pl

    monkeypatch.setattr(pl, "HISTORY", tmp_path / "runs.jsonl")

    class Sup:
        enabled = True
        status = {"slm": {"status": sup_status}}

    class Rt:
        vectors = None
        corpus = {}
        supervisor = Sup()

    Rt.llm = llm
    return pl.Pipeline(Rt(), generate_summary=None, log=lambda m: None)


def test_configured_but_unconfirmed_slm_is_not_ready(monkeypatch, tmp_path):
    # Regression: a stale LLM_BASE_URL in .env made the warm-up start before vLLM existed.
    from services.agents.dag import Skip

    p = _pipeline(monkeypatch, tmp_path, "starting")
    assert not p.slm_ready()
    with pytest.raises(Skip):
        p.agent_summarise({})
    assert _pipeline(monkeypatch, tmp_path, "ok").slm_ready()


def test_summarise_fails_when_every_job_fails(monkeypatch, tmp_path):
    from datetime import date, datetime, timezone

    from services.document_ingestion.corpus import CorpusDocument
    from services.document_ingestion.manifest import DocumentEntry

    class Down(Exception):
        code = "model_unavailable"

    p = _pipeline(monkeypatch, tmp_path, "ok")

    def gen(doc, lang, llm):
        raise Down("connection refused")

    p.generate_summary = gen
    entry = DocumentEntry.model_validate(dict(id="d1", state="MH", language="mr", document_type="gr", issued=date(2026, 1, 1),
                                              department="d", department_en="d", title="t", title_en="t",
                                              url="https://x.gov.in/a.pdf", listing_url="https://x.gov.in/", fetch={"method": "crawler"}))
    p.rt.corpus = {f"d{i}": CorpusDocument(entry=entry.model_copy(update={"id": f"d{i}"}), sha256="ab" * 32,
                                           retrieved_at=datetime.now(timezone.utc), pages=[], passages=[]) for i in range(5)}
    with pytest.raises(RuntimeError, match="stopped responding|all .* failed"):
        p.agent_summarise({})
