"""A small DAG runner for the ingestion workflow (crawl → import → index / summarise).

Each node is an agent: a function taking the shared run context and returning a JSON-serialisable
result. Independent nodes run in parallel; a node runs once all its dependencies succeeded, and is
``skipped`` (with the reason) if any dependency failed or was skipped. Failed nodes are retried with
a delay. Every state change is reported through ``on_update`` so the UI can show live progress.
A node may raise :class:`Skip` to declare it has nothing to do (e.g. Qdrant not configured).
"""

from __future__ import annotations

import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class Skip(Exception):
    """Raised by an agent that has nothing to do; the node is marked skipped, not failed."""


@dataclass
class Node:
    name: str
    run: Callable[[dict], Any]
    deps: tuple[str, ...] = ()
    retries: int = 0
    retry_delay_s: float = 5.0
    description: str = ""


@dataclass
class NodeState:
    name: str
    description: str
    deps: list[str]
    status: str = "pending"  # pending | running | succeeded | failed | skipped
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    result: Any = None
    error: str | None = None


@dataclass
class DagRun:
    dag: str
    trigger: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "running"  # running | succeeded | partial | failed
    started_at: str = field(default_factory=lambda: _now())
    finished_at: str | None = None
    nodes: dict[str, NodeState] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "dag": self.dag, "trigger": self.trigger, "status": self.status,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "nodes": [vars(n) for n in self.nodes.values()]}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate(nodes: list[Node]) -> None:
    names = [n.name for n in nodes]
    if len(names) != len(set(names)):
        raise ValueError("duplicate node names")
    known = set(names)
    for n in nodes:
        missing = set(n.deps) - known
        if missing:
            raise ValueError(f"{n.name}: unknown dependencies {sorted(missing)}")
    seen: set[str] = set()
    for _ in nodes:  # Kahn-style cycle check
        ready = [n.name for n in nodes if n.name not in seen and set(n.deps) <= seen]
        if not ready:
            break
        seen |= set(ready)
    if seen != known:
        raise ValueError(f"dependency cycle among {sorted(known - seen)}")


def run_dag(name: str, nodes: list[Node], context: dict | None = None, trigger: str = "manual",
            max_parallel: int = 4, on_update: Callable[[DagRun], None] | None = None,
            sleep: Callable[[float], None] = time.sleep) -> DagRun:
    validate(nodes)
    ctx = context if context is not None else {}
    run = DagRun(dag=name, trigger=trigger,
                 nodes={n.name: NodeState(n.name, n.description, list(n.deps)) for n in nodes})
    by_name = {n.name: n for n in nodes}
    notify = (lambda: on_update(run)) if on_update else (lambda: None)
    notify()

    def execute(node: Node) -> None:
        st = run.nodes[node.name]
        st.status, st.started_at = "running", _now()
        notify()
        t0 = time.monotonic()
        for attempt in range(node.retries + 1):
            st.attempts = attempt + 1
            try:
                st.result = node.run(ctx)
                st.status, st.error = "succeeded", None
                break
            except Skip as exc:
                st.status, st.result = "skipped", str(exc)
                break
            except Exception as exc:
                st.error = f"{type(exc).__name__}: {exc}"
                st.result = {"traceback": traceback.format_exc(limit=3)[-1500:]}
                if attempt < node.retries:
                    notify()
                    sleep(node.retry_delay_s)
                else:
                    st.status = "failed"
        st.finished_at, st.duration_s = _now(), round(time.monotonic() - t0, 2)
        notify()

    pending = set(by_name)
    futures: dict[Future, str] = {}
    with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix=f"dag-{name}") as pool:
        while pending or futures:
            for nm in sorted(pending):
                deps = [run.nodes[d].status for d in by_name[nm].deps]
                if any(s in ("failed", "skipped") for s in deps):
                    bad = [d for d in by_name[nm].deps if run.nodes[d].status in ("failed", "skipped")]
                    st = run.nodes[nm]
                    st.status, st.result = "skipped", f"dependency did not succeed: {', '.join(bad)}"
                    pending.discard(nm)
                    notify()
                elif all(s == "succeeded" for s in deps):
                    pending.discard(nm)
                    futures[pool.submit(execute, by_name[nm])] = nm
            if not futures:
                break
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for f in done:
                futures.pop(f)
                f.result()  # execute() never raises; surface programming errors if it does

    statuses = {n.status for n in run.nodes.values()}
    if "failed" not in statuses:
        run.status = "succeeded"
    else:
        run.status = "partial" if "succeeded" in statuses else "failed"
    run.finished_at = _now()
    notify()
    return run
