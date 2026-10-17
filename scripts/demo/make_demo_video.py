"""Records a demo video for one state from the running application (plan §8–10).

    python scripts/demo/make_demo_video.py --state MH --base-url http://localhost:8000 \
        [--question-audio data/demo/questions/MH.wav]

Requirements: the API running with a real model (LLM_BASE_URL) and TTS
(TTS_ENGINE=parler), and Playwright's Chromium installed.

What it guarantees:
- Real product footage only: every on-screen result comes from the running app.
- It refuses to record against a test/stub model, and aborts if an answer's
  status contradicts what the narration says will happen (scene `expect`).
- Narration is AI speech. A permanent on-screen label says so, the closing line
  says so, and the evidence file records the TTS model and voices.
- --question-audio must be a consented recording of a real person asking the
  scene question; it is fed to the browser as microphone input, so the real
  speech-recognition path is shown. Without it, the question is typed.

Outputs in output/demo/<state>/: demo_<state>.mp4 (1080p, AAC audio, soft
subtitles), captions.srt, narration.wav, evidence.json.
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCENES = ROOT / "docs" / "demo_scripts" / "scenes.yaml"
OUT = ROOT / "output" / "demo"
TEST_OUT = ROOT / "output" / "demo-TEST"
TEST_LABEL = "TEST RECORDING · NOT REAL MODEL OUTPUT · NOT FOR DISTRIBUTION"
SR = 44100
WIDTH, HEIGHT = 1920, 1080
ISO639_2 = {"mr": "mar", "hi": "hin", "or": "ori", "en": "eng"}
STUB_MODEL = re.compile(r"stub|fake|test|mock", re.I)
ANSWER_DONE = "#answer .claim, [data-testid=answer-insufficient], #answer .error"


class DemoAborted(RuntimeError):
    pass


# -- pure helpers (unit-tested) ---------------------------------------------

def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_srt(cues: list[tuple[float, float, str]]) -> str:
    blocks = [f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n" for i, (a, b, text) in enumerate(cues, start=1)]
    return "\n".join(blocks)


def resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x.astype(np.float32)
    n = int(round(x.size * sr_out / sr_in))
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def mix(duration_s: float, clips: list[tuple[float, np.ndarray, int]]) -> np.ndarray:
    """Place each (start_s, samples, sample_rate) clip on one mono track."""
    track = np.zeros(int(duration_s * SR) + 1, dtype=np.float32)
    for start, samples, sr in clips:
        x = resample(samples, sr)
        i = int(start * SR)
        end = min(i + x.size, track.size)
        track[i:end] += x[: end - i]
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    return track / peak * 0.95 if peak > 0.95 else track


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        sr, n, width = w.getframerate(), w.getnframes(), w.getsampwidth()
        raw = w.readframes(n)
        channels = w.getnchannels()
    if width != 2:
        raise ValueError("expected 16-bit PCM WAV")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, sr


def encode_wav(x: np.ndarray, sr: int = SR) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


# -- API access --------------------------------------------------------------

class Api:
    def __init__(self, base: str, key: str | None):
        self.base = base.rstrip("/") + "/api/v1"
        self.s = requests.Session()
        if key:
            self.s.headers["X-API-Key"] = key

    def get(self, path: str, **kw):
        r = self.s.get(self.base + path, timeout=600, **kw)
        return r.json() if "json" in r.headers.get("content-type", "") else r

    def post(self, path: str, body: dict):
        return self.s.post(self.base + path, json=body, timeout=900).json()

    def synth(self, text: str, lang: str, speaker: str) -> tuple[np.ndarray, int, dict]:
        job = self.post("/speech/synthesis", {"text": text, "language": lang, "speaker": speaker})
        if job.get("error"):
            raise DemoAborted(f"TTS unavailable: {job['error']['message']}")
        job_id = job["data"]["job_id"]
        for _ in range(900):
            status = self.get(f"/speech/synthesis/{job_id}")["data"]
            if status["status"] in ("done", "failed"):
                break
            time.sleep(1)
        if status["status"] != "done":
            raise DemoAborted(f"narration failed quality checks: {status.get('error')}")
        audio = self.s.get(f"{self.base}/speech/synthesis/{job_id}/audio", timeout=60).content
        x, sr = decode_wav(audio)
        return x, sr, status


def preflight(api: Api, state: str, video: dict, allow_test_model: bool = False) -> dict:
    health = api.get("/health")["data"]
    deps = {d["name"]: d for d in health["dependencies"]}
    slm = deps["slm"]
    if slm["status"] != "ok":
        raise DemoAborted(f"language model not available ({slm['status']})")
    if STUB_MODEL.search(slm.get("detail") or "") and not allow_test_model:
        raise DemoAborted(f"refusing to record with test model {slm['detail']!r}")
    if deps["tts"]["status"] != "ok":
        raise DemoAborted("TTS not available; start the API with TTS_ENGINE=parler")
    docs = api.get(f"/documents?state={state}")["data"]
    if not docs:
        raise DemoAborted(f"no document for {state} in the corpus")
    doc, lang = docs[0], video["language"]

    summary = api.post("/summaries", {"document_id": doc["id"], "language": lang})
    if summary.get("error") or summary["data"]["status"] != "summarised":
        raise DemoAborted(f"summary failed: {summary.get('error')}")
    answers = {}
    for scene in video["scenes"]:
        if scene["action"] != "ask":
            continue
        r = api.post("/qa", {"question": scene["question"], "language": lang, "document_id": doc["id"]})
        if r.get("error"):
            raise DemoAborted(f"Q&A failed for {scene['id']}: {r['error']['message']}")
        if r["data"]["status"] != scene["expect"]:
            raise DemoAborted(f"scene {scene['id']}: answer status {r['data']['status']!r} contradicts narration "
                              f"(expected {scene['expect']!r}); adjust the question or narration, then review")
        answers[scene["id"]] = r
    return {"document": doc, "model": slm["detail"], "summary": summary, "answers": answers}


# -- recording ---------------------------------------------------------------

OVERLAY_JS = """
(label) => {
  const style = document.createElement('style');
  style.textContent = `
    #demo-label{position:fixed;top:14px;right:18px;z-index:9999;background:rgba(75,42,138,.92);color:#fff;
      font:600 18px/1.3 var(--font);padding:8px 14px;border-radius:8px}
    #demo-caption{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:9999;max-width:1500px;
      background:rgba(20,24,33,.86);color:#fff;font:500 28px/1.45 var(--font);padding:12px 22px;border-radius:10px;
      text-align:center}
    #demo-caption:empty{display:none}
    .demo-focus{outline:4px solid #b5651d;outline-offset:4px;transition:outline .3s}`;
  document.head.appendChild(style);
  const l = document.createElement('div'); l.id = 'demo-label'; l.textContent = label; document.body.appendChild(l);
  const c = document.createElement('div'); c.id = 'demo-caption'; document.body.appendChild(c);
  window.__caption = t => { c.textContent = t; };
}
"""


def record(api: Api, base_url: str, state: str, video: dict, pre: dict, narration: dict,
           question_audio: Path | None, workdir: Path) -> tuple[Path, list, list, dict]:
    from playwright.sync_api import sync_playwright

    lang = video["language"]
    cues, clips, observed = [], [], {}
    args = []
    if question_audio:
        args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={question_audio.resolve()}%noloop"]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, record_video_dir=str(workdir),
                                  record_video_size={"width": WIDTH, "height": HEIGHT},
                                  permissions=["microphone"] if question_audio else [])
        page = ctx.new_page()
        t0 = time.monotonic()
        now = lambda: time.monotonic() - t0  # noqa: E731

        page.goto(f"{base_url}/?state={state}&lang={lang}")
        page.wait_for_selector("[data-testid=official-link]")
        page.evaluate(OVERLAY_JS, video["label"])
        page.wait_for_timeout(800)

        for scene in video["scenes"]:
            x, sr = narration[scene["id"]]
            start = now()
            clips.append((start, x, sr))
            page.evaluate("t => window.__caption(t)", " ".join(scene["narration"].split()))
            narr_end = start + x.size / sr
            action = scene["action"]

            if action == "home":
                pass
            elif action == "document":
                page.evaluate("document.querySelector('#doc-card').classList.add('demo-focus')")
                page.hover("[data-testid=official-link]")
            elif action == "summary":
                page.evaluate("document.querySelector('#doc-card').classList.remove('demo-focus')")
                page.click("[data-testid=btn-summary]")
                page.wait_for_selector("#summary .section", timeout=900_000)
                page.locator("#summary").scroll_into_view_if_needed()
            elif action == "ask":
                page.fill("[data-testid=question]", "")
                page.locator("[data-testid=question]").scroll_into_view_if_needed()
                if question_audio and scene.get("expect") == "answered" and "question_audio_used" not in observed:
                    qa_x, qa_sr = decode_wav(question_audio.read_bytes())
                    page.click("[data-testid=btn-mic]")
                    clips.append((now(), qa_x, qa_sr))
                    page.wait_for_timeout(int(qa_x.size / qa_sr * 1000) + 400)
                    page.click("[data-testid=btn-mic]")
                    page.wait_for_function("document.querySelector('[data-testid=question]').value.length > 0",
                                           timeout=120_000)
                    page.wait_for_timeout(1500)  # let viewers read and confirm the transcript
                    observed["question_audio_used"] = page.input_value("[data-testid=question]")
                else:
                    page.type("[data-testid=question]", scene["question"], delay=55)
                with page.expect_response(lambda r: r.url.endswith("/api/v1/qa")) as resp:
                    page.click("[data-testid=btn-ask]")
                status = resp.value.json()["data"]["status"]
                if status != scene["expect"]:
                    raise DemoAborted(f"during recording, scene {scene['id']} returned {status!r}")
                observed[scene["id"]] = resp.value.json()
                page.wait_for_selector(ANSWER_DONE, timeout=900_000)
            elif action == "listen_answer":
                page.wait_for_timeout(max(0, int((narr_end - now()) * 1000)) + 300)
                with page.expect_response(lambda r: r.url.endswith("/api/v1/speech/synthesis")) as resp:
                    page.click("[data-testid=listen-answer]")
                job_id = resp.value.json()["data"]["job_id"]
                page.wait_for_selector("[data-listen=answer] audio", timeout=900_000)
                play_at = now()
                y, ysr = decode_wav(api.s.get(f"{api.base}/speech/synthesis/{job_id}/audio", timeout=60).content)
                clips.append((play_at, y, ysr))
                observed["product_voice"] = api.get(f"/speech/synthesis/{job_id}")["data"]
                narr_end = play_at + y.size / ysr
            elif action == "open_citation":
                cite = page.locator("#answer [data-testid=cite]").first
                if cite.count() == 0:
                    cite = page.locator("#summary [data-testid=cite]").first
                cite.click()
                page.wait_for_selector("[data-testid=passage]")
                page.wait_for_timeout(600)
            elif action == "home_scroll_top":
                page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            else:
                raise DemoAborted(f"unknown action {action!r}")

            remaining = narr_end + 0.8 - now()
            if remaining > 0:
                page.wait_for_timeout(int(remaining * 1000))
            cues.append((start, now() - 0.1, " ".join(scene["narration"].split())))

        page.evaluate("window.__caption('')")
        page.wait_for_timeout(1200)
        total = now()
        ctx.close()
        video_path = Path(page.video.path())
        browser.close()
    observed["duration_s"] = total
    return video_path, cues, clips, observed


def compose(video_webm: Path, audio_wav: Path, srt: Path, lang: str, out_mp4: Path) -> None:
    import imageio_ffmpeg

    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-i", str(video_webm), "-i", str(audio_wav), "-i", str(srt),
           "-map", "0:v", "-map", "1:a", "-map", "2:s",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text",
           "-metadata:s:s:0", f"language={ISO639_2[lang]}", "-metadata:s:a:0", f"language={ISO639_2[lang]}",
           "-movflags", "+faststart", str(out_mp4)]
    subprocess.run(cmd, check=True)


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, choices=["MH", "MP", "OD"])
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--api-key")
    ap.add_argument("--question-audio", type=Path, help="consented recording of a real person asking the question")
    ap.add_argument("--allow-test-model", action="store_true",
                    help="pipeline smoke test: allows a stub model, stamps every frame NOT FOR DISTRIBUTION")
    args = ap.parse_args()

    video = yaml.safe_load(SCENES.read_text(encoding="utf-8"))["videos"][args.state]
    lang = video["language"]
    if args.allow_test_model:
        video["label"] = TEST_LABEL
    out = (TEST_OUT if args.allow_test_model else OUT) / args.state
    work = out / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    api = Api(args.base_url, args.api_key)

    try:
        print("pre-flight: model, TTS, summary and answers …")
        pre = preflight(api, args.state, video, args.allow_test_model)
        print("narration …")
        narration, voices = {}, {}
        for scene in video["scenes"]:
            x, sr, meta = api.synth(scene["narration"], lang, video["narrator"])
            narration[scene["id"]] = (x, sr)
            voices[scene["id"]] = meta
        print("recording …")
        webm, cues, clips, observed = record(api, args.base_url, args.state, video, pre, narration,
                                             args.question_audio, work)
    except DemoAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2

    track = mix(observed["duration_s"], clips)
    (out / "narration.wav").write_bytes(encode_wav(track))
    (out / "captions.srt").write_text(make_srt(cues), encoding="utf-8")
    mp4 = out / (f"TEST_NOT_FOR_DISTRIBUTION_{args.state}.mp4" if args.allow_test_model else f"demo_{args.state}.mp4")
    compose(webm, out / "narration.wav", out / "captions.srt", lang, mp4)

    evidence = {
        "state": args.state, "language": lang, "test_recording": args.allow_test_model, "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(), "document": pre["document"], "language_model": pre["model"],
        "summary": pre["summary"]["data"], "summary_sources": pre["summary"]["sources"],
        "answers_shown": {k: v for k, v in observed.items() if isinstance(v, dict) and "data" in v},
        "spoken_question_transcript": observed.get("question_audio_used"),
        "narration": {"synthetic": True, "speaker": video["narrator"],
                      "tts_model": next(iter(voices.values()))["model"]},
        "product_voice": observed.get("product_voice"),
        "on_screen_label": video["label"],
        "review_required": ["native-speaker review of narration and captions",
                            "check every number and date shown against the official PDF",
                            "sign-off by the responsible reviewer before client delivery"],
    }
    (out / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"done: {mp4.relative_to(ROOT)} ({observed['duration_s']:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
