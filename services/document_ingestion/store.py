"""Immutable, versioned document store (Workstream A, tasks 4, 6, 7, 8).

Original files are content-addressed by SHA-256 and never overwritten or
deleted. Every (URL, content) observation is recorded as a version with its
retrieval metadata, so:

- the same PDF under several URLs is stored once, with provenance for each URL;
- a PDF replaced at the same URL becomes a new version, the old one preserved;
- a failed fetch is logged and queued for retry, and never touches versions.

SQLite is the interim metadata backend; it moves to PostgreSQL in weeks 6–8.
"""

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

IngestStatus = Literal["new", "duplicate", "unchanged", "revised"]

RETRY_BASE = timedelta(minutes=15)
RETRY_MAX = timedelta(hours=24)

SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (
    sha256 TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS url_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    sha256 TEXT NOT NULL REFERENCES blobs(sha256),
    retrieved_at TEXT NOT NULL,
    last_checked_at TEXT NOT NULL,
    http_status INTEGER,
    content_type TEXT,
    etag TEXT,
    last_modified TEXT,
    is_current INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_per_url ON url_versions(url) WHERE is_current = 1;
CREATE TABLE IF NOT EXISTS fetch_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    failed_at TEXT NOT NULL,
    error TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retry_queue (
    url TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    counts TEXT
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class IngestResult:
    status: IngestStatus
    sha256: str
    previous_sha256: str | None = None


@dataclass(frozen=True)
class Freshness:
    sha256: str
    retrieved_at: datetime
    last_checked_at: datetime
    verified_fresh: bool
    last_error: str | None


class DocumentStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.blob_dir = self.root / "blobs"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / "metadata.sqlite3")
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- blobs -------------------------------------------------------------

    def blob_path(self, sha256: str) -> Path:
        return self.blob_dir / sha256[:2] / sha256

    def read_blob(self, sha256: str) -> bytes:
        return self.blob_path(sha256).read_bytes()

    def _write_blob(self, sha256: str, content: bytes) -> None:
        path = self.blob_path(sha256)
        if path.exists():
            return
        path.parent.mkdir(exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)

    # -- ingestion ---------------------------------------------------------

    def ingest(
        self,
        source_id: str,
        url: str,
        content: bytes,
        *,
        http_status: int | None = None,
        content_type: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        now: datetime | None = None,
    ) -> IngestResult:
        if not content:
            raise ValueError("refusing to ingest empty content")
        sha = hashlib.sha256(content).hexdigest()
        ts = (now or _utcnow()).isoformat()

        with self._db:
            row = self._db.execute(
                "SELECT sha256 FROM url_versions WHERE url = ? AND is_current = 1", (url,)
            ).fetchone()
            previous = row["sha256"] if row else None
            self._db.execute("DELETE FROM retry_queue WHERE url = ?", (url,))

            if previous == sha:
                self._db.execute(
                    "UPDATE url_versions SET last_checked_at = ? WHERE url = ? AND is_current = 1",
                    (ts, url),
                )
                return IngestResult("unchanged", sha)

            known = self._db.execute("SELECT 1 FROM blobs WHERE sha256 = ?", (sha,)).fetchone()
            if not known:
                self._write_blob(sha, content)
                self._db.execute(
                    "INSERT INTO blobs (sha256, size, first_seen_at) VALUES (?, ?, ?)",
                    (sha, len(content), ts),
                )
            if previous:
                self._db.execute("UPDATE url_versions SET is_current = 0 WHERE url = ? AND is_current = 1", (url,))
            self._db.execute(
                """INSERT INTO url_versions (source_id, url, sha256, retrieved_at, last_checked_at,
                       http_status, content_type, etag, last_modified, is_current)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (source_id, url, sha, ts, ts, http_status, content_type, etag, last_modified),
            )

        if previous:
            return IngestResult("revised", sha, previous)
        return IngestResult("duplicate" if known else "new", sha)

    def record_failure(
        self, source_id: str, url: str, error: str, *, retryable: bool = True, now: datetime | None = None
    ) -> None:
        """Log a failed fetch. Existing versions of the URL are left untouched."""
        at = now or _utcnow()
        with self._db:
            self._db.execute(
                "INSERT INTO fetch_failures (source_id, url, failed_at, error) VALUES (?, ?, ?, ?)",
                (source_id, url, at.isoformat(), error),
            )
            if not retryable:
                return
            row = self._db.execute("SELECT attempts FROM retry_queue WHERE url = ?", (url,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            delay = min(RETRY_BASE * 2 ** (attempts - 1), RETRY_MAX)
            self._db.execute(
                """INSERT INTO retry_queue (url, source_id, attempts, next_attempt_at, last_error)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET attempts = excluded.attempts,
                       next_attempt_at = excluded.next_attempt_at, last_error = excluded.last_error""",
                (url, source_id, attempts, (at + delay).isoformat(), error),
            )

    def due_retries(self, source_id: str, now: datetime | None = None) -> list[str]:
        rows = self._db.execute(
            "SELECT url FROM retry_queue WHERE source_id = ? AND next_attempt_at <= ? ORDER BY next_attempt_at",
            (source_id, (now or _utcnow()).isoformat()),
        ).fetchall()
        return [r["url"] for r in rows]

    # -- queries -----------------------------------------------------------

    def versions(self, url: str) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM url_versions WHERE url = ? ORDER BY id", (url,)).fetchall()

    def urls_for(self, sha256: str) -> list[str]:
        rows = self._db.execute("SELECT DISTINCT url FROM url_versions WHERE sha256 = ? ORDER BY url", (sha256,))
        return [r["url"] for r in rows]

    def freshness(self, url: str) -> Freshness | None:
        """Last good version of a URL, and whether a later fetch attempt failed."""
        cur = self._db.execute(
            "SELECT sha256, retrieved_at, last_checked_at FROM url_versions WHERE url = ? AND is_current = 1", (url,)
        ).fetchone()
        if cur is None:
            return None
        fail = self._db.execute(
            "SELECT error FROM fetch_failures WHERE url = ? AND failed_at > ? ORDER BY id DESC LIMIT 1",
            (url, cur["last_checked_at"]),
        ).fetchone()
        return Freshness(
            sha256=cur["sha256"],
            retrieved_at=datetime.fromisoformat(cur["retrieved_at"]),
            last_checked_at=datetime.fromisoformat(cur["last_checked_at"]),
            verified_fresh=fail is None,
            last_error=fail["error"] if fail else None,
        )

    # -- crawl runs --------------------------------------------------------

    def start_run(self, source_id: str) -> int:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO crawl_runs (source_id, started_at) VALUES (?, ?)", (source_id, _utcnow().isoformat())
            )
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str, counts: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE crawl_runs SET finished_at = ?, status = ?, counts = ? WHERE id = ?",
                (_utcnow().isoformat(), status, counts, run_id),
            )
