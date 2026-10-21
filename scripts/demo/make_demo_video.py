"""Records a narrated demo video for one state from the running application (plan §8–10).

    python scripts/demo/make_demo_video.py --state MH [--base-url http://localhost:8000] \
        [--question-audio data/demo/questions/MH.wav]

Requirements: the API running with a real model (LLM_BASE_URL) and TTS
(TTS_ENGINE=parler), and Playwright's Chromium installed.

How the video is made:
- Picture: Chrome's own screencast streams full-HD frames whenever the screen changes;
  each frame is time-stamped on the same clock as the narration and encoded with x264 at
  high quality (Playwright's built-in recorder is low-bitrate and looks blocky).
- Sound: narration is synthesized one sentence at a time, so captions and pauses follow
  the speech exactly; each scene starts its narration together with the on-screen action
  it describes and lasts until both have finished. The product's own answer voice is
  pre-generated, so "Listen" plays immediately in the video.
- The finished MP4 is checked for an audible audio track before it is reported done.

What it guarantees:
- Real product footage and real model output only. It refuses test/stub models (unless
  --allow-test-model, which stamps every frame NOT FOR DISTRIBUTION), and aborts if an
  answer's status contradicts what the narration says will happen (scene `expect`).
- Narration is AI speech, labelled on screen throughout and said aloud at the end.
- --question-audio must be a consented recording of a real person asking the scene
  question; it is fed to the browser as microphone input. Without it, the question is typed.

Outputs: output/demo/<STATE>/demo_<STATE>.mp4 (+ captions.srt, narration.wav,
evidence.json) and a copy of the video in output/demo/final/.
"""

import argparse
import asyncio
import base64
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import numpy as np
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.tts.normalise import sentences  # noqa: E402

SCENES = ROOT / "docs" / "demo_scripts" / "scenes.yaml"
OUT = ROOT / "output" / "demo"
TEST_OUT = ROOT / "output" / "demo-TEST"
TEST_LABEL = "TEST RECORDING · NOT REAL MODEL OUTPUT · NOT FOR DISTRIBUTION"
SR = 44100
WIDTH, HEIGHT = 1920, 1080
ISO639_2 = {"mr": "mar", "hi": "hin", "or": "ori", "en": "eng"}
LANGUAGE_NAMES = {"mr": "marathi", "hi": "hindi", "or": "odia", "en": "english"}
STUB_MODEL = re.compile(r"stub|fake|test|mock", re.I)
ANSWER_DONE = "#answer .claim, [data-testid=answer-insufficient], #answer .error"
SENTENCE_PAUSE_S = 0.45
SCENE_GAP_S = 0.75
MIN_MEAN_VOLUME_DB = -45.0


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
        i = max(0, int(start * SR))
        end = min(i + x.size, track.size)
        if end > i:
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


def concat_list(frames: list[tuple[float, str]], t_end: float) -> str:
    """ffmpeg concat-demuxer script that shows each frame until the next one arrives."""
    lines = ["ffconcat version 1.0"]
    for i, (ts, path) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else t_end
        lines += [f"file '{Path(path).as_posix()}'", f"duration {max(nxt - ts, 0.001):.4f}"]
    lines.append(f"file '{Path(frames[-1][1]).as_posix()}'")  # the demuxer needs the last file repeated
    return "\n".join(lines) + "\n"


# -- API access --------------------------------------------------------------

class Api:
    def __init__(self, base: str, key: str | None):
        self.base = base.rstrip("/") + "/api/v1"
        self.s = requests.Session()
        if key:
            self.s.headers["X-API-Key"] = key

    def get(self, path: str):
        return self.s.get(self.base + path, timeout=600).json()

    def post(self, path: str, body: dict):
        return self.s.post(self.base + path, json=body, timeout=900).json()

    def wait_job(self, job_id: str) -> dict:
        for _ in range(900):
            status = self.get(f"/speech/synthesis/{job_id}")["data"]
            if status["status"] in ("done", "failed"):
                return status
            time.sleep(1)
        return {"status": "failed", "error": "timeout"}

    def synth(self, text: str, lang: str, speaker: str | None) -> tuple[np.ndarray, int, dict]:
        job = self.post("/speech/synthesis", {"text": text, "language": lang, "speaker": speaker})
        if job.get("error"):
            raise DemoAborted(f"TTS unavailable: {job['error']['message']}")
        status = self.wait_job(job["data"]["job_id"])
        if status["status"] != "done":
            raise DemoAborted(f"speech failed its quality checks for {text[:40]!r}: {status.get('error')}")
        audio = self.s.get(f"{self.base}/speech/synthesis/{job['data']['job_id']}/audio", timeout=60).content
        x, sr = decode_wav(audio)
        return x, sr, status


def preflight(api: Api, state: str, video: dict, allow_test_model: bool = False) -> dict:
    health = api.get("/health")["data"]
    deps = {d["name"]: d for d in health["dependencies"]}
    slm = deps["slm"]
    if slm["status"] != "ok":
        raise DemoAborted(f"language model not available ({slm['status']}: {slm.get('detail')})")
    if STUB_MODEL.search(slm.get("detail") or "") and not allow_test_model:
        raise DemoAborted(f"refusing to record with test model {slm['detail']!r}")
    if deps["tts"]["status"] != "ok":
        raise DemoAborted("TTS not available; start the API with TTS_ENGINE=parler")
    docs = api.get(f"/documents?state={state}")["data"]
    if not docs:
        raise DemoAborted(f"no document for {state} in the corpus")
    # The scenes are written for the curated demo documents; crawled GRs listed first must not replace them.
    from services.document_ingestion.manifest import load_manifest
    curated = {e.id for e in load_manifest()}
    doc, lang = next((d for d in docs if d["id"] in curated), docs[0]), video["language"]
    video["_document_id"] = doc["id"]

    summary = api.post("/summaries", {"document_id": doc["id"], "language": lang})
    if summary.get("error") or summary["data"]["status"] != "summarised":
        raise DemoAborted(f"summary failed: {summary.get('error')}")
    stated = [s["key"] for s in summary["data"]["sections"] if s["status"] == "stated"]
    print(f"  summary: {len(stated)} sections stated ({', '.join(stated)}), "
          f"{summary['data']['removed_claims']} unsupported statements removed")

    # Check every question scene before recording anything, and report all of them. Model
    # output varies slightly between calls, so a mismatch is retried once (bypassing the
    # answer cache); the checked answer is cached, so the recording shows exactly it.
    answers, problems = {}, []
    for scene in video["scenes"]:
        if scene["action"] != "ask":
            continue
        for attempt in (1, 2):
            path = "/qa" if attempt == 1 else "/qa?refresh=true"
            r = api.post(path, {"question": scene["question"], "language": lang, "document_id": doc["id"]})
            if r.get("error"):
                raise DemoAborted(f"Q&A failed for {scene['id']}: {r['error']['message']}")
            if r["data"]["status"] == scene["expect"]:
                break
        status = r["data"]["status"]
        shown = " ".join(c["text"] for c in r["data"]["claims"]) or "; ".join(u["message"] for u in r["uncertainties"])
        mark = "ok " if status == scene["expect"] else "MISMATCH"
        print(f"  [{mark}] {scene['id']}: {scene['question']}\n         -> {status}: {shown[:300]}")
        if status != scene["expect"]:
            problems.append(f"scene {scene['id']}: got {status!r}, narration expects {scene['expect']!r}")
        answers[scene["id"]] = r
    if problems:
        raise DemoAborted("; ".join(problems) + ". Review the answers above; adjust the question in "
                          "docs/demo_scripts/scenes.yaml if the model's answer is reasonable")

    # Pre-generate the product's spoken answer exactly as the UI will request it, so the
    # "Listen" click in the recording plays at once instead of leaving silence.
    for scene_id, r in answers.items():
        if r["data"]["status"] == "answered":
            text = " ".join(c["text"] for c in r["data"]["claims"])
            api.synth(text, lang, None)
            print(f"  product voice ready for {scene_id}")
    return {"document": doc, "model": slm["detail"], "summary": summary, "answers": answers}


def prepare_narration(api: Api, video: dict) -> dict:
    """Per scene: [(sentence, samples, sr)], one TTS call per sentence for exact timing."""
    out = {}
    for scene in video["scenes"]:
        text = " ".join(scene["narration"].split())
        parts = []
        for sentence in sentences(text, max_chars=200):
            x, sr, _ = api.synth(sentence, video["language"], video["narrator"])
            parts.append((sentence, x, sr))
        out[scene["id"]] = parts
        total = sum(x.size / sr for _, x, sr in parts) + SENTENCE_PAUSE_S * (len(parts) - 1)
        print(f"  narration {scene['id']}: {len(parts)} sentences, {total:.1f}s")
    return out


# -- recording ---------------------------------------------------------------

OVERLAY_JS = r"""
(cfg) => {
  const style = document.createElement('style');
  style.textContent = `
    #demo-label{position:fixed;bottom:24px;right:24px;z-index:10001;background:rgba(30,41,59,.92);color:#f1f5f9;
      font:600 15px/1.3 var(--font, system-ui, sans-serif);padding:7px 14px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.25);
      backdrop-filter:blur(8px);max-width:320px;letter-spacing:0.2px;}
    #demo-caption{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:10001;max-width:1100px;
      background:rgba(15,23,42,.92);color:#ffffff;font:500 23px/1.45 var(--font, system-ui, sans-serif);padding:10px 24px;border-radius:12px;
      text-align:center;transition:opacity .25s;box-shadow:0 4px 20px rgba(0,0,0,.35);backdrop-filter:blur(8px);letter-spacing:0.2px;}
    #demo-caption:empty{opacity:0;pointer-events:none;}
    #demo-cursor{position:fixed;left:0;top:0;z-index:10002;width:30px;height:30px;pointer-events:none;
      transform:translate(960px,600px);transition:opacity .4s;filter:drop-shadow(0 3px 6px rgba(0,0,0,.4))}
    .demo-ripple{position:fixed;z-index:10001;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;
      border:3px solid #b5651d;pointer-events:none;animation:demo-ripple .6s ease-out forwards}
    @keyframes demo-ripple{to{transform:scale(3.4);opacity:0}}
    .demo-focus{outline:4px solid #b5651d !important;outline-offset:6px;border-radius:12px;transition:outline-color .3s}
    #demo-card{position:fixed;inset:0;z-index:10000;display:flex;flex-direction:column;align-items:center;
      justify-content:center;gap:22px;background:linear-gradient(135deg,#071e3d,#0f4c81 55%,#1d6aa8);color:#fff;
      transition:opacity .85s ease;font-family:var(--font, system-ui, sans-serif);text-align:center}
    #demo-card .t{font:700 78px/1.25 var(--font, system-ui, sans-serif)}
    #demo-card .s{font:400 38px/1.4 var(--font, system-ui, sans-serif);opacity:.92}
    #demo-card .f{font:500 24px/1.4 var(--font, system-ui, sans-serif);opacity:.85;margin-top:24px}
    #demo-card .e{font-size:100px}`;
  document.head.appendChild(style);
  const add = (tag, id, html) => { const e = document.createElement(tag); e.id = id; if (html) e.innerHTML = html; document.body.appendChild(e); return e; };
  const label = add('div', 'demo-label'); label.textContent = cfg.label;
  const caption = add('div', 'demo-caption');
  const cursor = add('div', 'demo-cursor',
    '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M4 2 L4 20 L9 15.5 L12.5 22 L15.5 20.5 L12 14 L19 14 Z" fill="#fff" stroke="#0f172a" stroke-width="1.8" stroke-linejoin="round"/></svg>');
  const card = add('div', 'demo-card');
  const pos = {x: 960, y: 600};

  // Heartbeat to keep compositor painting at steady cadence
  let hb = 0;
  const dot = document.createElement('div');
  dot.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0.01;pointer-events:none;';
  document.body.appendChild(dot);
  const beat = () => { hb++; dot.textContent = hb % 2 === 0 ? '.' : ' '; requestAnimationFrame(beat); };
  requestAnimationFrame(beat);

  window.__demo = {
    caption: t => { caption.textContent = t; },
    moveTo: (x, y, ms) => {
      cursor.style.transition = `transform ${ms}ms cubic-bezier(.35,.1,.25,1)`;
      cursor.style.transform = `translate(${x}px, ${y}px)`; pos.x = x; pos.y = y;
    },
    click: () => {
      const r = document.createElement('div'); r.className = 'demo-ripple';
      r.style.left = (pos.x + 4) + 'px'; r.style.top = (pos.y + 3) + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 700);
    },
    card: (title, subtitle, footer) => {
      cursor.style.opacity = '0';
      card.innerHTML = `<div class="e">📜</div><div class="t"></div><div class="s"></div><div class="f"></div>`;
      card.querySelector('.t').textContent = title; card.querySelector('.s').textContent = subtitle;
      card.querySelector('.f').textContent = footer; card.style.display = 'flex';
      requestAnimationFrame(() => { card.style.opacity = '1'; });
    },
    hideCard: () => { card.style.opacity = '0'; cursor.style.opacity = '1'; setTimeout(() => { card.style.display = 'none'; }, 950); },
    focus: (sel, on) => { const e = document.querySelector(sel); if (e) e.classList.toggle('demo-focus', on); },
    scrollTo: (y, ms) => new Promise(done => {
      const y0 = window.scrollY, t0 = performance.now();
      const step = now => {
        const k = Math.min(1, (now - t0) / ms), ease = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        window.scrollTo(0, y0 + (y - y0) * ease);
        k < 1 ? requestAnimationFrame(step) : done();
      };
      requestAnimationFrame(step);
    }),
  };
  window.__demo.card(cfg.title, cfg.subtitle, cfg.label);
}
"""


class Recorder:
    """Drives the UI for one video; frames and audio share the time.time() clock."""

    def __init__(self, page, cdp, frames_dir: Path):
        self.page, self.cdp, self.dir = page, cdp, frames_dir
        self.frames: list[tuple[float, str]] = []

    async def start(self):
        self.cdp.on("Page.screencastFrame", lambda p: asyncio.ensure_future(self._frame(p)))
        await self.cdp.send("Page.startScreencast", {"format": "png", "maxWidth": WIDTH,
                                                     "maxHeight": HEIGHT, "everyNthFrame": 1})
        for _ in range(100):
            if self.frames:
                return
            await asyncio.sleep(0.05)
        raise DemoAborted("the browser screencast produced no frames")

    async def _frame(self, params):
        ts = time.time()
        path = self.dir / f"f{len(self.frames):06d}.png"
        path.write_bytes(base64.b64decode(params["data"]))
        self.frames.append((ts, str(path)))
        try:
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:
            pass  # the session is closing

    async def stop(self):
        try:
            await self.cdp.send("Page.stopScreencast")
        except Exception:
            pass

    # -- gestures --------------------------------------------------------------

    async def until(self, t: float):
        delay = t - time.time()
        if delay > 0:
            await asyncio.sleep(delay)

    async def glide(self, selector: str, ms: int = 750):
        loc = self.page.locator(selector).first
        await loc.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center'})")
        await asyncio.sleep(0.7)
        box = await loc.bounding_box()
        if box:
            x, y = box["x"] + min(box["width"] * 0.5, 120), box["y"] + box["height"] * 0.5
            await self.page.evaluate("([x, y, ms]) => __demo.moveTo(x, y, ms)", [x, y, ms])
            await asyncio.sleep(ms / 1000 + 0.1)
        return loc

    async def click(self, selector: str):
        loc = await self.glide(selector)
        await self.page.evaluate("__demo.click()")
        await asyncio.sleep(0.15)
        await loc.click()

    async def captions(self, start: float, timeline: list[tuple[float, float, str]]):
        for offset, dur, text in timeline:
            await self.until(start + offset)
            await self.page.evaluate("t => __demo.caption(t)", text)
            await self.until(start + offset + dur)
        await self.page.evaluate("__demo.caption('')")


async def record(api: Api, base_url: str, state: str, video: dict, narration: dict,
                 question_audio: Path | None, frames_dir: Path) -> tuple[list, float, float, list, list, dict]:
    from playwright.async_api import async_playwright

    lang = video["language"]
    cues, clips, observed = [], [], {}
    args = [
        f"--window-size={WIDTH},{HEIGHT}",
        "--force-device-scale-factor=1",
        "--disable-features=Translate",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    if question_audio:
        args += ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 f"--use-file-for-fake-audio-capture={question_audio.resolve()}%noloop"]
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=args)
        ctx = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1,
                                        permissions=["microphone"] if question_audio else [])
        page = await ctx.new_page()
        doc_param = f"&doc={video['_document_id']}" if video.get("_document_id") else ""
        await page.goto(f"{base_url}/?state={state}&lang={lang}{doc_param}")
        await page.wait_for_selector("[data-testid=official-link]")
        card = video["card"]
        await page.evaluate(OVERLAY_JS, {"label": video["label"], "title": card["title"], "subtitle": card["subtitle"]})
        await asyncio.sleep(1.0)  # let the title card fade in
        rec = Recorder(page, await ctx.new_cdp_session(page), frames_dir)
        await rec.start()
        t0 = rec.frames[0][0]
        await asyncio.sleep(0.8)

        for scene in video["scenes"]:
            start = time.time()
            timeline, offset = [], 0.0
            for text, x, sr in narration[scene["id"]]:
                dur = x.size / sr
                clips.append((start + offset - t0, x, sr))
                timeline.append((offset, dur, text))
                cues.append((start + offset - t0, start + offset + dur - t0, text))
                offset += dur + SENTENCE_PAUSE_S
            narr_end = start + offset - SENTENCE_PAUSE_S
            caption_task = asyncio.create_task(rec.captions(start, timeline))
            action = scene["action"]
            dur_total = narr_end - start

            if action == "title_card":
                await rec.until(narr_end + 0.3)
                await page.evaluate("__demo.hideCard()")
                await asyncio.sleep(1.0)
            elif action == "overview":
                await rec.until(start + 0.15 * dur_total)
                await rec.glide(f"[data-testid=state-{state}]")
                await rec.until(start + 0.55 * dur_total)
                await rec.glide("[data-testid=language]")
            elif action == "document":
                await page.evaluate("__demo.focus('#doc-card', true)")
                await rec.glide("#doc-card h1")
                await rec.until(start + 0.5 * dur_total)
                await rec.glide("#doc-card .badges")
                await rec.until(start + 0.8 * dur_total)
                await rec.glide("[data-testid=official-link]")
            elif action == "summary":
                await page.evaluate("__demo.focus('#doc-card', false)")
                await rec.until(start + 0.12 * dur_total)
                await rec.click("[data-testid=btn-summary]")
                await page.wait_for_selector("#summary .section", timeout=900_000)
                box = await page.locator("#summary").bounding_box()
                top = await page.evaluate("window.scrollY")
                target = top + (box["y"] if box else 0) - 140
                await page.evaluate("y => __demo.scrollTo(y, 1200)", target)
                remaining = max(2.0, narr_end - time.time() - 1.0)
                height = await page.evaluate("document.querySelector('#summary').scrollHeight")
                await page.evaluate("([y, ms]) => __demo.scrollTo(y, ms)", [target + max(0, height - 600), int(remaining * 1000)])
            elif action == "open_citation":
                await rec.click("#summary [data-testid=cite]")
                await page.wait_for_selector("[data-testid=passage]")
                await page.evaluate("__demo.focus('#source-panel', true)")
                await rec.until(narr_end)
                await page.evaluate("__demo.focus('#source-panel', false)")
            elif action == "ask":
                await rec.click("[data-testid=question]")
                await page.fill("[data-testid=question]", "")
                if question_audio and scene.get("expect") == "answered" and "question_audio_used" not in observed:
                    qa_x, qa_sr = decode_wav(question_audio.read_bytes())
                    await rec.click("[data-testid=btn-mic]")
                    clips.append((time.time() - t0, qa_x, qa_sr))
                    await asyncio.sleep(qa_x.size / qa_sr + 0.4)
                    await page.click("[data-testid=btn-mic]")
                    await page.wait_for_function("document.querySelector('[data-testid=question]').value.length > 0",
                                                 timeout=120_000)
                    await asyncio.sleep(1.5)  # time to read and confirm the transcript
                    observed["question_audio_used"] = await page.input_value("[data-testid=question]")
                else:
                    await page.type("[data-testid=question]", scene["question"], delay=65)
                    await asyncio.sleep(0.4)
                async with page.expect_response(lambda r: r.url.endswith("/api/v1/qa")) as resp_info:
                    await rec.click("[data-testid=btn-ask]")
                resp = await resp_info.value
                body = await resp.json()
                if body["data"]["status"] != scene["expect"]:
                    raise DemoAborted(f"during recording, scene {scene['id']} returned {body['data']['status']!r}")
                observed[scene["id"]] = body
                await page.wait_for_selector(ANSWER_DONE, timeout=900_000)
                await rec.glide("#answer")
            elif action == "listen_answer":
                await rec.until(narr_end + 0.2)
                await caption_task
                async with page.expect_response(lambda r: r.url.endswith("/api/v1/speech/synthesis")) as resp_info:
                    await rec.click("[data-testid=listen-answer]")
                job_id = (await (await resp_info.value).json())["data"]["job_id"]
                await page.wait_for_selector("[data-listen=answer] audio", timeout=900_000)
                play_at = time.time()
                wav = await asyncio.to_thread(lambda: api.s.get(f"{api.base}/speech/synthesis/{job_id}/audio", timeout=60).content)
                y, ysr = decode_wav(wav)
                clips.append((play_at - t0, y, ysr))
                observed["product_voice"] = await asyncio.to_thread(api.get, f"/speech/synthesis/{job_id}")
                narr_end = play_at + y.size / ysr
            elif action == "closing_card":
                await page.evaluate("y => __demo.scrollTo(0, 900)", 0)
                await page.evaluate("([t, s, f]) => __demo.card(t, s, f)", [card["title"], card["subtitle"], card["closing"]])
            else:
                raise DemoAborted(f"unknown action {action!r}")

            await rec.until(narr_end + SCENE_GAP_S)
            if not caption_task.done():
                await caption_task

        await asyncio.sleep(1.5)
        t_end = time.time()
        await rec.stop()
        await asyncio.sleep(0.2)
        frames = list(rec.frames)
        await browser.close()
    return frames, t0, t_end, cues, clips, observed


# -- assembly ----------------------------------------------------------------

def ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def assemble(frames: list, t0: float, t_end: float, audio_wav: Path, srt: Path, lang: str, workdir: Path,
             out_mp4: Path) -> None:
    listing = workdir / "frames.ffconcat"
    listing.write_text(concat_list(frames, t_end), encoding="utf-8")
    cmd = [ffmpeg(), "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio_wav),
           "-map", "0:v", "-map", "1:a",
           "-vf", f"scale={WIDTH}:{HEIGHT}:flags=lanczos:in_range=pc:out_range=tv,fps=30,format=yuv420p",
           "-fps_mode", "cfr",
           "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-level:v", "4.1",
           "-g", "60", "-keyint_min", "30", "-sc_threshold", "0",
           "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
           "-disposition:a:0", "default",
           "-metadata:s:a:0", f"language={ISO639_2[lang]}",
           "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
           "-t", f"{t_end - t0:.2f}", "-movflags", "+faststart", str(out_mp4)]
    subprocess.run(cmd, check=True)


def verify(mp4: Path) -> dict:
    """Confirm the MP4 has a 1080p video stream and an audible audio stream."""
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(mp4), "-af", "volumedetect", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = proc.stderr
    has_video = re.search(r"Video: h264.*1920x1080", log) is not None
    has_audio = re.search(r"Audio: aac", log) is not None
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", log)
    duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", log)
    seconds = int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3)) if duration else 0
    info = {"video_1080p_h264": has_video, "audio_aac": has_audio,
            "mean_volume_db": float(mean.group(1)) if mean else None, "duration_s": round(seconds, 1)}
    if not (has_video and has_audio and mean and float(mean.group(1)) > MIN_MEAN_VOLUME_DB):
        raise DemoAborted(f"the finished video failed its checks: {info}")
    return info


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
    if args.allow_test_model:
        video["label"] = TEST_LABEL
    lang = video["language"]
    out = (TEST_OUT if args.allow_test_model else OUT) / args.state
    work = out / "work"
    shutil.rmtree(work, ignore_errors=True)  # may leave files behind if something holds a lock
    (work / "frames").mkdir(parents=True, exist_ok=True)
    for stale in (work / "frames").glob("*.*"):
        stale.unlink(missing_ok=True)
    api = Api(args.base_url, args.api_key)

    try:
        print(f"[{args.state}] pre-flight: model, TTS, summary and answers …")
        pre = preflight(api, args.state, video, args.allow_test_model)
        print(f"[{args.state}] narration …")
        narration = prepare_narration(api, video)
        print(f"[{args.state}] recording …")
        frames, t0, t_end, cues, clips, observed = asyncio.run(
            record(api, args.base_url, args.state, video, narration, args.question_audio, work / "frames"))
        print(f"[{args.state}] {len(frames)} frames over {t_end - t0:.0f}s; mixing and encoding …")
        (out / "narration.wav").write_bytes(encode_wav(mix(t_end - t0, clips)))
        (out / "captions.srt").write_text(make_srt(cues), encoding="utf-8")
        name = f"demo_{args.state}_{LANGUAGE_NAMES[lang]}"
        if args.allow_test_model:
            name = f"TEST_NOT_FOR_DISTRIBUTION_{name}"
        mp4 = out / f"{name}.mp4"
        assemble(frames, t0, t_end, out / "narration.wav", out / "captions.srt", lang, work, mp4)
        checks = verify(mp4)
    except DemoAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2

    final = (TEST_OUT if args.allow_test_model else OUT) / "final"
    final.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp4, final / mp4.name)
    shutil.copy2(out / "captions.srt", final / f"{mp4.stem}.srt")

    evidence = {
        "state": args.state, "language": lang, "test_recording": args.allow_test_model,
        "created_at": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit(),
        "document": pre["document"], "language_model": pre["model"],
        "summary": pre["summary"]["data"], "summary_sources": pre["summary"]["sources"],
        "answers_shown": {k: v for k, v in observed.items() if isinstance(v, dict) and "data" in v},
        "spoken_question_transcript": observed.get("question_audio_used"),
        "narration": {"synthetic": True, "speaker": video["narrator"], "tts_model": "ai4bharat/indic-parler-tts"},
        "product_voice": observed.get("product_voice"),
        "on_screen_label": video["label"], "video_checks": checks,
        "review_required": ["native-speaker review of narration and captions",
                            "check every number and date shown against the official PDF",
                            "sign-off by the responsible reviewer before client delivery"],
    }
    (out / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(f"[{args.state}] done: {(final / mp4.name).relative_to(ROOT)} "
          f"({checks['duration_s']:.0f}s, audio {checks['mean_volume_db']} dB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
