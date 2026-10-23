"""Agent farm: a pool of identical workers processing a queue of jobs in parallel.

Used to pre-generate summaries: vLLM batches concurrent requests, so N workers give close to N
times the throughput of a sequential loop. Each job's outcome is recorded; one failing job never
stops the others. ``should_stop`` lets the farm drain early (e.g. the SLM went down).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FarmReport:
    workers: int
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"workers": self.workers, "total": self.total, "done": self.done, "failed": self.failed,
                "skipped": self.skipped, "outcomes": self.outcomes, "errors": self.errors[-10:]}


def run_farm(jobs: Iterable[Any], worker: Callable[[Any], str], workers: int = 4,
             label: Callable[[Any], str] = str, should_stop: Callable[[], bool] = lambda: False,
             on_progress: Callable[[FarmReport], None] | None = None) -> FarmReport:
    """Run ``worker(job)`` for every job; the worker returns a short outcome label (e.g. "generated")."""
    jobs = list(jobs)
    report = FarmReport(workers=max(1, workers), total=len(jobs))
    lock = threading.Lock()

    def guarded(job):
        if should_stop():
            return job, "stopped", None
        try:
            return job, worker(job), None
        except Exception as exc:
            return job, "failed", f"{label(job)}: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=report.workers, thread_name_prefix="farm") as pool:
        for fut in as_completed([pool.submit(guarded, j) for j in jobs]):
            _, outcome, error = fut.result()
            with lock:
                report.outcomes[outcome] = report.outcomes.get(outcome, 0) + 1
                if error:
                    report.failed += 1
                    report.errors.append(error)
                elif outcome == "stopped":
                    report.skipped += 1
                else:
                    report.done += 1
            if on_progress:
                on_progress(report)
    return report
