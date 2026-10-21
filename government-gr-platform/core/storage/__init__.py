"""Content-addressed object storage for original PDFs and derived artifacts.

Originals are written once under ``originals/<sha[:2]>/<sha>.pdf`` and never overwritten;
derived files (e.g. OCR'd searchable PDFs) live under ``derived/``.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import Protocol

from core.config.settings import get_settings


def original_key(sha256: str) -> str:
    return f"originals/{sha256[:2]}/{sha256}.pdf"


def derived_key(sha256: str, kind: str) -> str:
    return f"derived/{kind}/{sha256[:2]}/{sha256}.pdf"


class ObjectStore(Protocol):
    def exists(self, key: str) -> bool: ...
    def put_file(self, key: str, path: Path, content_type: str = "application/pdf") -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def open_path(self, key: str) -> Path:
        """Return a local filesystem path with the object's content (may be a temp copy)."""
        ...


class LocalObjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"invalid object key {key!r}")
        return p

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def put_file(self, key: str, path: Path, content_type: str = "application/pdf") -> None:
        dest = self._path(key)
        if dest.exists():  # write-once: never overwrite an existing object
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(path, "rb") as src, open(tmp, "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)
        os.replace(tmp, dest)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open_path(self, key: str) -> Path:
        return self._path(key)


class MinioObjectStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool):
        from minio import Minio

        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self.client.stat_object(self.bucket, key)
            return True
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return False
            raise

    def put_file(self, key: str, path: Path, content_type: str = "application/pdf") -> None:
        if self.exists(key):
            return
        self.client.fput_object(self.bucket, key, str(path), content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def open_path(self, key: str) -> Path:
        fd, name = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.get_bytes(key))
        return Path(name)

    def stream(self, key: str) -> io.BufferedIOBase:
        return self.client.get_object(self.bucket, key)


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        s = get_settings()
        if s.storage_backend == "minio":
            _store = MinioObjectStore(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, s.minio_bucket, s.minio_secure)
        else:
            _store = LocalObjectStore(s.local_storage_dir)
    return _store


def set_store(store: ObjectStore | None) -> None:
    global _store
    _store = store
