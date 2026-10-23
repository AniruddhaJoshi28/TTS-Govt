"""Supervisor logic against stand-ins: fake launch scripts + tiny HTTP servers imitating vLLM and
the speech service (the real services need a GPU)."""

import json
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from apps.api import supervisor as sup

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash needed for launch scripts")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve(port: int, routes: dict) -> HTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(json.dumps(body or {}).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Rt:
    llm = None
    tts = stt = None
    tts_error = stt_error = None

    def load_speech(self):
        pass


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    d = tmp_path / "gpu"
    d.mkdir()
    monkeypatch.setattr(sup, "SCRIPTS", d)
    monkeypatch.setattr(sup, "LOGS", tmp_path / "logs")
    monkeypatch.setenv("SERVICE_START_TIMEOUT", "20")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    def write(name, body):
        (d / name).write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
    return write


def make(monkeypatch) -> sup.Supervisor:
    s = sup.Supervisor(Rt(), log=lambda m: None)
    s.enabled = True  # the host check (Linux) is bypassed for the test
    monkeypatch.setattr(s, "_wait", lambda check, *a: _poll(check))
    return s


def _poll(check, tries=100):
    import time
    for _ in range(tries):
        try:
            r = check()
            if r:
                return r
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("not healthy")


def test_slm_model_id_comes_from_the_running_server(scripts, monkeypatch):
    port = free_port()
    srv = serve(port, {"/v1/models": {"data": [{"id": "Qwen/Qwen3-4B"}]}})
    scripts("start_slm.sh", f'echo "started {port} whatever-config-says"')
    scripts("start_speech.sh", "exit 1")
    s = make(monkeypatch)
    s.ensure_slm()
    srv.shutdown()
    assert s.status["slm"]["status"] == "ok"
    assert s.rt.llm.model == "Qwen/Qwen3-4B"  # discovered, not configured
    assert s.rt.llm.config.base_url == f"http://127.0.0.1:{port}/v1"


def test_speech_service_wires_remote_engines(scripts, monkeypatch):
    port = free_port()
    srv = serve(port, {"/health": {"tts": {"status": "ok"}, "stt": {"status": "unavailable", "detail": "no model"}}})
    scripts("start_speech.sh", f'echo "started {port}"')
    scripts("start_slm.sh", "exit 1")
    s = make(monkeypatch)
    s.ensure_speech()
    srv.shutdown()
    assert isinstance(s.rt.tts, sup.RemoteSpeech) and s.rt.stt is None and s.rt.stt_error == "no model"
    assert s.status["speech"]["status"] == "ok"


def test_launch_failure_is_reported_not_raised(scripts, monkeypatch):
    scripts("start_slm.sh", 'echo "error not enough free GPU memory" >&2; exit 1')
    scripts("start_speech.sh", "exit 1")
    s = make(monkeypatch)
    s.ensure_slm()
    assert s.status["slm"]["status"] == "unavailable" and "GPU memory" in s.status["slm"]["detail"]
    assert s.rt.llm is None
