"""Model-service supervisor: `uvicorn apps.api.main:app` brings up the SLM and the speech service.

* SLM    — vLLM, started by scripts/gpu/start_slm.sh (GPU/model/memory plan from env.sh).
* Speech — apps/speech_service (TTS + STT) in its own process, by scripts/gpu/start_speech.sh.

Both run as separate, detached processes: the web app serves immediately while models load, a
crash in a model process cannot take the web app down, and `uvicorn --reload` does not reload
multi-GB models. A watchdog re-checks health and restarts a service that has died.
Stop everything with scripts/gpu/stop_all.sh.

Environment:
    SERVICE_SUPERVISOR   auto (default) | off      auto = on when bash + the launch scripts exist
    SPEECH_MODE          service (default) | inprocess   inprocess = load TTS/STT inside the web app
    SERVICE_START_TIMEOUT  seconds to wait for a model service to become healthy (default 1800)
    SERVICE_WATCH_INTERVAL seconds between watchdog checks (default 30)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import requests

from services.stt.service import AudioRejected, Transcript
from services.tts.service import AudioQualityError, SpeechResult

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "gpu"
LOGS = Path(os.environ.get("LOGS", ROOT / "logs"))


class RemoteSpeech:
    """Client for apps/speech_service; same results as the in-process engines."""

    def __init__(self, base_url: str, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.model_id = "speech-service"

    def health(self) -> dict:
        return self.session.get(f"{self.base_url}/health", timeout=5).json()

    def synthesize(self, text: str, language: str, speaker: str | None = None) -> SpeechResult:
        r = self.session.post(f"{self.base_url}/synthesize", timeout=self.timeout,
                              json={"text": text, "language": language, "speaker": speaker})
        if r.status_code == 422:
            raise AudioQualityError(r.json().get("detail", "audio quality check failed"))
        r.raise_for_status()
        return SpeechResult(wav=r.content, duration_s=float(r.headers.get("X-Duration", 0)),
                            model=r.headers.get("X-Model", ""), voice=r.headers.get("X-Voice", ""), spoken_text=text)

    def transcribe(self, data: bytes, language: str) -> Transcript:
        r = self.session.post(f"{self.base_url}/transcribe", params={"language": language}, data=data,
                              timeout=self.timeout, headers={"Content-Type": "application/octet-stream"})
        if r.status_code == 422:
            raise AudioRejected(r.json().get("detail", "audio rejected"))
        r.raise_for_status()
        j = r.json()
        return Transcript(j["text"], j["language"], float(j["duration_s"]), j["model"])


def _tail(path: Path, n: int = 6) -> str:
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                 if any(k in ln for k in ("Error", "ERROR", "error:", "memory", "CUDA"))]
        return " | ".join(lines[-n:])[-600:]
    except OSError:
        return ""


class Supervisor:
    def __init__(self, runtime, log=print):
        self.rt = runtime
        self.log = log
        mode = os.environ.get("SERVICE_SUPERVISOR", "auto").lower()
        scripts_ok = (SCRIPTS / "start_slm.sh").is_file() and (SCRIPTS / "start_speech.sh").is_file()
        self.enabled = mode != "off" and os.name == "posix" and shutil.which("bash") is not None and scripts_ok
        self.speech_mode = os.environ.get("SPEECH_MODE", "service").lower()
        self.timeout = float(os.environ.get("SERVICE_START_TIMEOUT", "1800"))
        self.interval = float(os.environ.get("SERVICE_WATCH_INTERVAL", "30"))
        self.status: dict[str, dict] = {"slm": {"status": "not_configured"}, "speech": {"status": "not_configured"}}
        self._stop = threading.Event()
        self._locks = {"slm": threading.Lock(), "speech": threading.Lock()}

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        if not self.enabled:
            self.log("ℹ️ [SUPERVISOR] off (SERVICE_SUPERVISOR=off, non-Linux host, or launch scripts missing); "
                     "using LLM_BASE_URL and in-process speech")
            self.rt.load_speech()
            return
        threading.Thread(target=self.ensure_slm, name="ensure-slm", daemon=True).start()
        if self.speech_mode == "inprocess":
            threading.Thread(target=self.rt.load_speech, name="load-speech", daemon=True).start()
        else:
            threading.Thread(target=self.ensure_speech, name="ensure-speech", daemon=True).start()
        threading.Thread(target=self._watch, name="service-watchdog", daemon=True).start()

    def stop(self) -> None:
        # Model services are left running on purpose (fast restarts); scripts/gpu/stop_all.sh stops them.
        self._stop.set()

    def _launch(self, script: str) -> tuple[str, list[str]]:
        proc = subprocess.run(["bash", str(SCRIPTS / script)], capture_output=True, text=True, timeout=300, cwd=ROOT)
        out = (proc.stdout.strip().splitlines() or [""])[-1].split()
        if proc.returncode != 0 or not out:
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-600:] or f"{script} failed")
        return out[0], out[1:]

    def _wait(self, check, name: str, logfile: Path, pidfile: Path):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                result = check()
                if result:
                    return result
            except requests.RequestException:
                pass
            if pidfile.is_file():
                try:
                    os.kill(int(pidfile.read_text().strip()), 0)
                except (OSError, ValueError):
                    raise RuntimeError(f"{name} exited during startup: {_tail(logfile)}") from None
            time.sleep(5)
        raise RuntimeError(f"{name} did not become healthy within {self.timeout:.0f}s; see {logfile}")

    # -- SLM -----------------------------------------------------------------------------
    def ensure_slm(self) -> None:
        from services.slm_orchestrator.llm import LLMConfig, OpenAICompatibleLLM

        with self._locks["slm"]:
            try:
                self.status["slm"] = {"status": "starting", "detail": "checking / launching vLLM"}
                state, rest = self._launch("start_slm.sh")
                port = rest[0]
                base = f"http://127.0.0.1:{port}/v1"
                self.log(f"🧠 [SUPERVISOR] SLM {state} on port {port}; waiting until it serves requests …")

                def served():
                    r = requests.get(f"{base}/models", timeout=5)
                    return r.json()["data"][0]["id"] if r.status_code == 200 else None

                model = self._wait(served, "SLM (vLLM)", LOGS / "vllm.log", LOGS / "vllm.pid")
                cfg = LLMConfig.from_env() or LLMConfig(base_url=base)
                # The model id comes from the running server, not from configuration.
                self.rt.llm = OpenAICompatibleLLM(cfg.model_copy(update={"base_url": base, "model": model}))
                os.environ["LLM_BASE_URL"] = base
                self.status["slm"] = {"status": "ok", "detail": f"{model} @ {port}"}
                self.log(f"🧠 [SUPERVISOR] SLM ready: {model} on port {port}")
            except Exception as exc:
                self.status["slm"] = {"status": "unavailable", "detail": str(exc)[:600]}
                self.log(f"❌ [SUPERVISOR] SLM unavailable: {exc}")

    # -- speech --------------------------------------------------------------------------
    def ensure_speech(self) -> None:
        with self._locks["speech"]:
            try:
                self.status["speech"] = {"status": "starting", "detail": "loading TTS/STT models"}
                state, rest = self._launch("start_speech.sh")
                port = rest[0]
                client = RemoteSpeech(f"http://127.0.0.1:{port}")
                self.log(f"🔊 [SUPERVISOR] speech service {state} on port {port}; waiting for models …")
                health = self._wait(client.health, "speech service", LOGS / "speech.log", LOGS / "speech.pid")
                tts, stt = health.get("tts", {}), health.get("stt", {})
                self.rt.tts = client if tts.get("status") == "ok" else None
                self.rt.tts_error = None if self.rt.tts else tts.get("detail")
                self.rt.stt = client if stt.get("status") == "ok" else None
                self.rt.stt_error = None if self.rt.stt else stt.get("detail")
                self.status["speech"] = {"status": "ok" if self.rt.tts else "unavailable",
                                         "detail": f"port {port}; tts={tts.get('status')} stt={stt.get('status')}"}
                self.log(f"🔊 [SUPERVISOR] speech service ready on port {port} (tts={tts.get('status')}, stt={stt.get('status')})")
            except Exception as exc:
                self.rt.tts = self.rt.stt = None
                self.rt.tts_error = self.rt.stt_error = str(exc)[:600]
                self.status["speech"] = {"status": "unavailable", "detail": str(exc)[:600]}
                self.log(f"❌ [SUPERVISOR] speech service unavailable: {exc}")

    # -- watchdog --------------------------------------------------------------------------
    def _alive(self, name: str) -> bool:
        try:
            if name == "slm":
                return self.rt.llm is not None and requests.get(f"{self.rt.llm.config.base_url}/models", timeout=5).ok
            return isinstance(self.rt.tts, RemoteSpeech) and bool(self.rt.tts.health())
        except (requests.RequestException, ValueError):
            return False

    def _watch(self) -> None:
        while not self._stop.wait(self.interval):
            for name, ensure in (("slm", self.ensure_slm), ("speech", self.ensure_speech)):
                if name == "speech" and self.speech_mode == "inprocess":
                    continue
                if self.status[name]["status"] == "ok" and not self._alive(name):
                    self.log(f"⚠️ [SUPERVISOR] {name} stopped responding; restarting")
                    threading.Thread(target=ensure, daemon=True).start()
