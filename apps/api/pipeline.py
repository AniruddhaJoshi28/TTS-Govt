"""Ingestion workflow: agents wired into DAGs, a scheduler, and run history.

Workflows (DAGs):
    full  crawl ─▶ import ─▶ reload ─┬▶ index      (Qdrant, per state & language)
                                     └▶ summarise  (agent farm: parallel SLM workers)
    warm  index, summarise           (no crawl; fills Qdrant and the summary cache)

Agents:
    crawl      runs the government-gr-platform crawler (all active sources from its sources.yaml)
    import     imports newly archived PDFs into the corpus (OCR where the text layer is broken)
    reload     reloads the in-memory corpus and keyword indexes
    index      embeds new/changed passages into Qdrant
    summarise  pre-generates summaries so a click in the UI is a cache hit

Environment (all optional):
    PIPELINE_INTERVAL_MINUTES  full run every N minutes (default 180; 0 = only on demand)
    PIPELINE_RUN_ON_START      1 = run "full" once the SLM is ready (default 0)
    WARM_ON_START              1 = run "warm" once the SLM is ready (default 1)
    WARM_LANGUAGES             "native" (each GR's own language) and/or codes, e.g. "native,en"
    SUMMARY_WORKERS            parallel summary workers (default 4)
    CRAWL_MAX_PAGES / CRAWL_DOWNLOAD_LIMIT   per-source crawl bounds (default 2 / 30)
    GR_PLATFORM_DIR / GR_PLATFORM_PYTHON     crawler location / interpreter (auto-detected)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from schemas.api.envelope import Language
from services.agents.dag import DagRun, Node, Skip, run_dag
from services.agents.farm import run_farm
from services.document_ingestion.crawled_import import PLATFORM, import_crawled
from services.retrieval.vector_store import sync_corpus

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / "data" / "pipeline" / "runs.jsonl"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def platform_python() -> str:
    explicit = os.environ.get("GR_PLATFORM_PYTHON")
    candidates = [explicit] if explicit else []
    for base in (PLATFORM, ROOT):
        candidates += [str(base / ".venv" / "bin" / "python"), str(base / ".venv" / "Scripts" / "python.exe")]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return sys.executable


class Pipeline:
    def __init__(self, rt, generate_summary: Callable, log: Callable[[str], None] = print):
        self.rt, self.generate_summary, self.log = rt, generate_summary, log
        self.current: DagRun | None = None
        self.history: deque[dict] = deque(self._load_history(), maxlen=30)
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # -- agents ----------------------------------------------------------------------------
    def agent_crawl(self, ctx: dict) -> dict:
        if not (PLATFORM / "apps" / "crawler" / "cli.py").is_file():
            raise Skip(f"crawler not found at {PLATFORM}")
        cmd = [platform_python(), "-m", "apps.crawler.cli", "crawl-active",
               "--max-pages", str(_env_int("CRAWL_MAX_PAGES", 2)),
               "--download-limit", str(_env_int("CRAWL_DOWNLOAD_LIMIT", 30))]
        env = dict(os.environ)
        home = Path.home()
        if (home / "ocr-env" / "bin").is_dir():  # OCR tools installed without root, kept after the venv
            env["PATH"] = env.get("PATH", "") + os.pathsep + str(home / "ocr-env" / "bin")
            env.setdefault("TESSDATA_PREFIX", str(home / "tessdata"))
        proc = subprocess.run(cmd, cwd=PLATFORM, capture_output=True, text=True, env=env,
                              timeout=_env_int("CRAWL_TIMEOUT_S", 3600))
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-800:] or "crawler failed")
        try:
            runs = json.loads(proc.stdout)
        except json.JSONDecodeError:
            runs = proc.stdout.strip()[-400:]
        return {"sources": len(runs) if isinstance(runs, dict) else None, "crawl_runs": runs}

    def agent_import(self, ctx: dict) -> dict:
        stats, imported = import_crawled(corpus=self.rt.corpus_dir, log=lambda m: self.log(f"   {m}"))
        ctx["imported"] = imported
        return stats

    def agent_reload(self, ctx: dict) -> dict:
        self.rt.reload(index=False)  # the index agent embeds; reload only rebuilds the corpus + BM25
        return {"documents": len(self.rt.corpus)}

    def agent_index(self, ctx: dict) -> dict:
        if self.rt.vectors is None:
            raise Skip("Qdrant not configured (QDRANT_URL)")
        stats = sync_corpus(self.rt.vectors, list(self.rt.corpus.values()),
                            on_progress=lambda doc_id, n: self.log(f"🧭 [QDRANT] indexed {doc_id} ({n} passages)"))
        self.rt.vector_status = {"status": "ok" if not stats["failed"] else "degraded", "detail": stats}
        return stats

    def agent_summarise(self, ctx: dict) -> dict:
        llm = self.rt.llm
        if llm is None:
            raise Skip("SLM not ready")
        wanted = [w.strip() for w in os.environ.get("WARM_LANGUAGES", "native").split(",") if w.strip()]
        jobs = []
        for doc in self.rt.corpus.values():
            for w in wanted:
                lang = doc.entry.language.value if w == "native" else w
                try:
                    jobs.append((doc, Language(lang)))
                except ValueError:
                    continue
        model_down = {"n": 0}

        def work(job) -> str:
            doc, lang = job
            try:
                env, hit = self.generate_summary(doc, lang, llm)
            except Exception as exc:
                if getattr(exc, "code", "") in ("model_unavailable", "model_not_configured"):
                    model_down["n"] += 1
                raise
            model_down["n"] = 0
            return "cached" if hit else env.get("data", {}).get("status", "generated")

        report = run_farm(jobs, work, workers=_env_int("SUMMARY_WORKERS", 4),
                          label=lambda j: f"{j[0].entry.id}/{j[1].value}",
                          should_stop=lambda: model_down["n"] >= 3)
        return report.as_dict()

    # -- workflows -------------------------------------------------------------------------
    def nodes(self, dag: str) -> list[Node]:
        index = Node("index", self.agent_index, description="Embed passages into Qdrant (per state & language)")
        summarise = Node("summarise", self.agent_summarise, description="Pre-generate summaries (agent farm)")
        if dag == "warm":
            return [index, summarise]
        if dag == "full":
            return [
                Node("crawl", self.agent_crawl, retries=1, retry_delay_s=60, description="Crawl official portals"),
                Node("import", self.agent_import, ("crawl",), description="Import new PDFs into the corpus (OCR)"),
                Node("reload", self.agent_reload, ("import",), description="Reload corpus and keyword index"),
                Node(index.name, index.run, ("reload",), description=index.description),
                Node(summarise.name, summarise.run, ("reload",), description=summarise.description),
            ]
        raise ValueError(f"unknown workflow {dag!r} (use full or warm)")

    def start(self, dag: str, trigger: str = "manual") -> DagRun | None:
        """Start a workflow in the background. Returns None if one is already running."""
        nodes = self.nodes(dag)
        if not self._lock.acquire(blocking=False):
            return None
        run_holder: dict = {}

        def update(run: DagRun) -> None:
            self.current = run
            run_holder["run"] = run

        def body():
            try:
                self.log(f"🧩 [PIPELINE] {dag} workflow started ({trigger})")
                run = run_dag(dag, nodes, {}, trigger=trigger, on_update=update)
                self.history.appendleft(run.to_dict())
                self._save(run.to_dict())
                self.log(f"🧩 [PIPELINE] {dag} workflow {run.status}: "
                         + ", ".join(f"{n.name}={n.status}" for n in run.nodes.values()))
            finally:
                self._lock.release()

        threading.Thread(target=body, name=f"pipeline-{dag}", daemon=True).start()
        for _ in range(50):  # wait briefly so the caller gets the run id
            if "run" in run_holder:
                break
            time.sleep(0.02)
        return run_holder.get("run")

    @property
    def running(self) -> bool:
        return self._lock.locked()

    # -- scheduling ------------------------------------------------------------------------
    def start_scheduler(self) -> None:
        threading.Thread(target=self._schedule, name="pipeline-scheduler", daemon=True).start()

    def _wait_for_slm(self) -> bool:
        deadline = time.monotonic() + _env_int("SERVICE_START_TIMEOUT", 1800)
        while time.monotonic() < deadline and not self._stop.is_set():
            if self.rt.llm is not None:
                return True
            time.sleep(5)
        return False

    def _schedule(self) -> None:
        on_start = ("full" if os.environ.get("PIPELINE_RUN_ON_START") == "1"
                    else "warm" if os.environ.get("WARM_ON_START", "1") == "1" else None)
        if on_start and self._wait_for_slm():
            self.start(on_start, trigger="startup")
        minutes = _env_int("PIPELINE_INTERVAL_MINUTES", 180)
        if minutes <= 0:
            return
        while not self._stop.wait(minutes * 60):
            if self.start("full", trigger="schedule") is None:
                self.log("🧩 [PIPELINE] scheduled run skipped: a workflow is already running")

    def stop(self) -> None:
        self._stop.set()

    # -- history ---------------------------------------------------------------------------
    def _load_history(self) -> list[dict]:
        try:
            lines = HISTORY.read_text(encoding="utf-8").splitlines()[-30:]
            return [json.loads(ln) for ln in reversed(lines) if ln.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, run: dict) -> None:
        try:
            HISTORY.parent.mkdir(parents=True, exist_ok=True)
            with HISTORY.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(run, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def snapshot(self) -> dict:
        running = self.running
        current = self.current.to_dict() if running and self.current else None
        return {"running": running, "current": current,
                "history": [r for r in self.history if not current or r["id"] != current["id"]][:10],
                "workflows": {name: [{"name": n.name, "deps": list(n.deps), "description": n.description}
                                     for n in self.nodes(name)] for name in ("full", "warm")},
                "interval_minutes": _env_int("PIPELINE_INTERVAL_MINUTES", 180)}
