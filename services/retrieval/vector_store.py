"""Qdrant vector index: one collection per state (GOVT_MH, GOVT_MP, GOVT_OD, GOVT_UP).

Each point is one citable passage. The payload carries the passage text plus the GR's metadata
(title, department, date, number, official URL, language, version), so the collection is a
self-describing store of every GR's chunks. Point ids are derived from passage ids, so re-indexing
is an idempotent upsert; a new document version replaces the old points.

Embeddings run locally (fastembed / ONNX, CPU) — no paid API. Default model:
``intfloat/multilingual-e5-large`` (covers Marathi, Hindi, Odia, English; needs the
"query: " / "passage: " prefixes it was trained with).

Configuration (environment):
    QDRANT_URL                e.g. https://rcp-qdrant.infoapps.io   (unset = vector search off, BM25 only)
    QDRANT_API_KEY            optional
    QDRANT_COLLECTION_PREFIX  default "GOVT_"
    EMBED_MODEL               default intfloat/multilingual-e5-large
    VECTOR_MIN_SCORE          cosine floor for dense hits (default 0.80, calibrated for e5)
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from services.retrieval.bm25 import BM25Index, Hit

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "intfloat/multilingual-e5-large"
_NS = uuid.UUID("5b1f5e2a-8d0e-4c1b-9a51-6f7c2f3e9d10")
BATCH = 64

Embedder = Callable[[list[str]], list[list[float]]]


def point_id(passage_id: str) -> str:
    return str(uuid.uuid5(_NS, passage_id))


class FastEmbedder:
    """Lazy-loaded local embedding model with e5-style prefixes."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model_name = model
        self._model = None
        self._lock = threading.Lock()
        self.e5 = "e5" in model.lower()

    def _local_model_dir(self) -> str:
        """Download the ONNX model as real files (no HF-cache symlinks) into a persistent directory.

        Large models keep weights in a separate ``model.onnx_data`` file; recent onnxruntime refuses
        to load external data reached through a symlink into another blob directory ("External data
        path escapes model directory"), which is how the Hugging Face cache stores files.
        """
        from fastembed import TextEmbedding
        from huggingface_hub import snapshot_download

        spec = next(m for m in TextEmbedding.list_supported_models() if m["model"] == self.model_name)
        root = Path(os.environ.get("EMBED_CACHE_DIR", Path.home() / ".cache" / "gr-embeddings"))
        target = root / self.model_name.replace("/", "__")
        files = [spec["model_file"], *spec.get("additional_files", [])]
        if not all((target / f).is_file() for f in files):
            snapshot_download(repo_id=spec["sources"]["hf"], local_dir=str(target))
        return str(target)

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                # CPU unless EMBED_CUDA=1 (needs fastembed-gpu + matching CUDA/cuDNN). "auto" would try
                # CUDA and log errors on hosts whose onnxruntime-gpu does not match the installed CUDA.
                cuda = os.environ.get("EMBED_CUDA") == "1"
                self._model = TextEmbedding(
                    self.model_name, specific_model_path=self._local_model_dir(), cuda=cuda,
                    providers=None if cuda else ["CPUExecutionProvider"],
                    threads=int(os.environ.get("EMBED_THREADS", "0")) or None)
        return self._model

    @property
    def dim(self) -> int:
        return len(self.embed_queries(["dimension probe"])[0])

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefix = "passage: " if self.e5 else ""
        return [v.tolist() for v in self._load().embed([prefix + t for t in texts], batch_size=BATCH)]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        prefix = "query: " if self.e5 else ""
        return [v.tolist() for v in self._load().embed([prefix + t for t in texts])]


class VectorStore:
    def __init__(self, client, embedder, prefix: str = "GOVT_", min_score: float = 0.80):
        from qdrant_client import models

        self.client, self.embedder, self.prefix, self.min_score = client, embedder, prefix, min_score
        self.m = models
        self._ready: set[str] = set()
        self._dim: int | None = None

    @classmethod
    def from_env(cls) -> VectorStore | None:
        url = os.environ.get("QDRANT_URL", "").strip()
        if not url:
            return None
        from qdrant_client import QdrantClient

        # Only the core REST API (collections, upsert, query_points, scroll) is used, which is stable
        # across 1.x; skip the strict client/server minor-version check (server here is 1.14).
        client = QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY") or None, timeout=30,
                              port=None if url.startswith("http") else 6333, check_compatibility=False)
        return cls(client, FastEmbedder(os.environ.get("EMBED_MODEL", DEFAULT_MODEL)),
                   prefix=os.environ.get("QDRANT_COLLECTION_PREFIX", "GOVT_"),
                   min_score=float(os.environ.get("VECTOR_MIN_SCORE", "0.80")))

    def collection(self, state: str) -> str:
        return f"{self.prefix}{state}"

    def ensure(self, state: str) -> str:
        name = self.collection(state)
        if name in self._ready:
            return name
        if not self.client.collection_exists(name):
            if self._dim is None:
                self._dim = self.embedder.dim
            self.client.create_collection(name, vectors_config=self.m.VectorParams(size=self._dim, distance=self.m.Distance.COSINE))
            for field, schema in (("document_id", self.m.PayloadSchemaType.KEYWORD),
                                  ("version_id", self.m.PayloadSchemaType.KEYWORD),
                                  ("language", self.m.PayloadSchemaType.KEYWORD),
                                  ("issued", self.m.PayloadSchemaType.KEYWORD)):
                self.client.create_payload_index(name, field, field_schema=schema)
        self._ready.add(name)
        return name

    def indexed_versions(self, state: str) -> dict[str, str]:
        """document_id -> version_id currently stored for a state."""
        name = self.ensure(state)
        found: dict[str, str] = {}
        offset = None
        while True:
            points, offset = self.client.scroll(name, limit=1000, offset=offset, with_vectors=False,
                                                with_payload=["document_id", "version_id"])
            for p in points:
                found[p.payload["document_id"]] = p.payload["version_id"]
            if offset is None:
                return found

    def index_document(self, doc) -> int:
        """Replace all points of ``doc`` (a CorpusDocument) with its current passages."""
        e = doc.entry
        name = self.ensure(e.state.value)
        doc_filter = self.m.Filter(must=[self.m.FieldCondition(key="document_id", match=self.m.MatchValue(value=e.id))])
        self.client.delete(name, points_selector=self.m.FilterSelector(filter=doc_filter), wait=True)
        passages = [p for p in doc.passages if p["text"].strip()]
        meta = {"state": e.state.value, "language": e.language.value, "title": e.title, "title_en": e.title_en,
                "department": e.department, "document_type": e.document_type, "issued": e.issued.isoformat(),
                "url": str(e.url), "listing_url": str(e.listing_url), "sha256": doc.sha256,
                **{f"meta_{k}": v for k, v in e.portal_metadata.items()}}
        for i in range(0, len(passages), BATCH):
            batch = passages[i:i + BATCH]
            vectors = self.embedder.embed_passages([p["text"] for p in batch])
            self.client.upsert(name, wait=True, points=[
                self.m.PointStruct(id=point_id(p["passage_id"]), vector=v, payload={
                    **meta, "document_id": e.id, "version_id": p["version_id"], "passage_id": p["passage_id"],
                    "page": p["page"], "origin": p["origin"], "text": p["text"],
                    "untrusted": [list(s) for s in p["untrusted"]]})
                for p, v in zip(batch, vectors)])
        return len(passages)

    def delete_document(self, state: str, document_id: str) -> None:
        name = self.ensure(state)
        self.client.delete(name, wait=True, points_selector=self.m.FilterSelector(filter=self.m.Filter(
            must=[self.m.FieldCondition(key="document_id", match=self.m.MatchValue(value=document_id))])))

    def search(self, query: str, state: str, k: int = 10, document_id: str | None = None) -> list[tuple[str, float]]:
        """(passage_id, cosine score) pairs above ``min_score``."""
        name = self.ensure(state)
        flt = None
        if document_id:
            flt = self.m.Filter(must=[self.m.FieldCondition(key="document_id", match=self.m.MatchValue(value=document_id))])
        vector = self.embedder.embed_queries([query])[0]
        res = self.client.query_points(name, query=vector, limit=k, query_filter=flt, with_payload=["passage_id"],
                                       score_threshold=self.min_score)
        return [(p.payload["passage_id"], p.score) for p in res.points]


class HybridIndex:
    """BM25 + dense retrieval fused with reciprocal-rank fusion; same interface as BM25Index.

    Dense hits are mapped back to the in-memory corpus passages, so a stale vector can never cite
    text that is not in the current document version. Any vector-store failure degrades to BM25.
    """

    RRF_K = 60

    def __init__(self, bm25: BM25Index, store: VectorStore | None, state: str, document_id: str | None = None):
        self.bm25, self.store, self.state, self.document_id = bm25, store, state, document_id
        self.passages = bm25.passages
        self._by_id = {p.passage_id: p for p in bm25.passages}
        self.last_mode = "bm25"

    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> list[Hit]:
        lexical = self.bm25.search(query, k=k * 3, min_score=min_score)
        dense: list[tuple[str, float]] = []
        if self.store is not None:
            try:
                dense = [(pid, s) for pid, s in self.store.search(query, self.state, k=k * 3, document_id=self.document_id)
                         if pid in self._by_id]
            except Exception as exc:  # network, missing collection, model load failure
                logger.warning("vector search unavailable, using BM25 only: %s", exc)
        self.last_mode = "hybrid" if dense else "bm25"
        if not dense:
            return lexical[:k]
        scores: dict[str, float] = {}
        for rank, h in enumerate(lexical):
            scores[h.passage.passage_id] = scores.get(h.passage.passage_id, 0) + 1 / (self.RRF_K + rank + 1)
        for rank, (pid, _) in enumerate(dense):
            scores[pid] = scores.get(pid, 0) + 1 / (self.RRF_K + rank + 1)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [Hit(self._by_id[pid], round(score * 1000, 3)) for pid, score in ranked]


def sync_corpus(store: VectorStore, docs: Iterable, on_progress: Callable[[str, int], None] | None = None,
                prune: bool = False) -> dict[str, int]:
    """Index documents whose current version is not yet in Qdrant.

    ``prune`` also deletes documents that are not in this corpus. Off by default: several app
    instances (laptop, server) may share one Qdrant, and pruning from a partial corpus would
    delete the other instance's documents.
    """
    stats = {"indexed": 0, "up_to_date": 0, "removed": 0, "failed": 0}
    by_state: dict[str, list] = {}
    for d in docs:
        by_state.setdefault(d.entry.state.value, []).append(d)
    for state, state_docs in by_state.items():
        stored = store.indexed_versions(state)
        current = {d.entry.id for d in state_docs}
        for d in state_docs:
            if stored.get(d.entry.id) == d.sha256[:12]:
                stats["up_to_date"] += 1
                continue
            try:
                n = store.index_document(d)
                stats["indexed"] += 1
                if on_progress:
                    on_progress(d.entry.id, n)
            except Exception as exc:
                stats["failed"] += 1
                logger.warning("indexing %s failed: %s", d.entry.id, exc)
        for doc_id in (set(stored) - current) if prune else ():
            store.delete_document(state, doc_id)
            stats["removed"] += 1
    return stats
