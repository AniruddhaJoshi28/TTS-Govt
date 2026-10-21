"""Qdrant vector store + hybrid retrieval, using Qdrant's in-memory mode (no server)."""

from datetime import date, datetime, timezone

import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from services.document_ingestion.corpus import CorpusDocument, PageRecord  # noqa: E402
from services.document_ingestion.manifest import DocumentEntry  # noqa: E402
from services.retrieval.bm25 import BM25Index, tokenize  # noqa: E402
from services.retrieval.vector_store import HybridIndex, VectorStore, sync_corpus  # noqa: E402


class HashEmbedder:
    """Deterministic bag-of-words vectors: shared words => high cosine similarity."""

    dim = 64

    def _vec(self, text):
        v = [0.0] * self.dim
        for w in tokenize(text):
            v[hash(w) % self.dim] += 1.0
        return v if any(v) else [1e-6] * self.dim

    def embed_passages(self, texts):
        return [self._vec(t) for t in texts]

    def embed_queries(self, texts):
        return [self._vec(t) for t in texts]


def make_doc(doc_id, state, texts, sha="ab" * 32):
    entry = DocumentEntry.model_validate(dict(
        id=doc_id, state=state, language={"MH": "mr", "MP": "hi", "OD": "or"}[state], document_type="gr",
        issued=date(2026, 10, 1), department="विभाग", department_en="Dept", title=f"शीर्षक {doc_id}", title_en="t",
        url="https://gr.maharashtra.gov.in/a.pdf", listing_url="https://gr.maharashtra.gov.in/list",
        fetch={"method": "crawler"}, portal_metadata={"Document number": "123"}))
    passages = [dict(passage_id=f"{doc_id}:p1:{i}", document_id=doc_id, version_id=sha[:12], url=str(entry.url),
                     page=1, text=t, origin="ocr", untrusted=[]) for i, t in enumerate(texts, 1)]
    return CorpusDocument(entry=entry, sha256=sha, retrieved_at=datetime.now(timezone.utc),
                          pages=[PageRecord(page=1, origin="ocr", text=" ".join(texts))], passages=passages)


@pytest.fixture
def store():
    return VectorStore(qdrant_client.QdrantClient(":memory:"), HashEmbedder(), prefix="GOVT_", min_score=0.1)


def test_one_collection_per_state_with_metadata_payload(store):
    stats = sync_corpus(store, [make_doc("mh1", "MH", ["शेतकरी अनुदान योजना"]), make_doc("od1", "OD", ["ଛାତ୍ରାବାସ ସଂକଳ୍ପ"])])
    assert stats == {"indexed": 2, "up_to_date": 0, "removed": 0, "failed": 0}
    names = {c.name for c in store.client.get_collections().collections}
    assert {"GOVT_MH", "GOVT_OD"} <= names
    point = store.client.scroll("GOVT_MH", limit=1, with_payload=True)[0][0]
    assert point.payload["title"] == "शीर्षक mh1" and point.payload["meta_Document number"] == "123"
    assert point.payload["state"] == "MH" and point.payload["language"] == "mr"


def test_sync_is_idempotent_and_reindexes_new_versions(store):
    doc = make_doc("mh1", "MH", ["शेतकरी अनुदान योजना", "पाणी पुरवठा"])
    sync_corpus(store, [doc])
    assert sync_corpus(store, [doc])["up_to_date"] == 1
    v2 = make_doc("mh1", "MH", ["सुधारित अनुदान"], sha="cd" * 32)
    assert sync_corpus(store, [v2])["indexed"] == 1
    points = store.client.scroll("GOVT_MH", limit=10, with_payload=True)[0]
    assert len(points) == 1 and points[0].payload["version_id"] == "cd" * 6  # old version's points replaced


def test_prune_is_opt_in(store):
    sync_corpus(store, [make_doc("mh1", "MH", ["a b c"]), make_doc("mh2", "MH", ["d e f"])])
    assert sync_corpus(store, [make_doc("mh1", "MH", ["a b c"])])["removed"] == 0
    assert sync_corpus(store, [make_doc("mh1", "MH", ["a b c"])], prune=True)["removed"] == 1


def test_document_filter_scopes_search(store):
    sync_corpus(store, [make_doc("mh1", "MH", ["शेतकरी अनुदान योजना"]), make_doc("mh2", "MH", ["शेतकरी अनुदान वितरण"])])
    hits = store.search("शेतकरी अनुदान", "MH", document_id="mh2")
    assert hits and all(pid.startswith("mh2:") for pid, _ in hits)


def test_hybrid_fuses_and_only_cites_current_passages(store):
    doc = make_doc("mh1", "MH", ["शेतकरी अनुदान योजना जाहीर", "रस्ते दुरुस्ती निधी"])
    sync_corpus(store, [doc])
    bm25 = BM25Index(doc.to_passages())
    hybrid = HybridIndex(bm25, store, "MH", "mh1")
    hits = hybrid.search("अनुदान योजना", k=2)
    assert hybrid.last_mode == "hybrid" and hits[0].passage.passage_id == "mh1:p1:1"
    # A passage present in Qdrant but not in the in-memory corpus is never returned.
    stale = HybridIndex(BM25Index([p for p in doc.to_passages() if p.passage_id != "mh1:p1:1"]), store, "MH", "mh1")
    assert all(h.passage.passage_id != "mh1:p1:1" for h in stale.search("अनुदान योजना", k=3))


def test_hybrid_degrades_to_bm25_when_qdrant_fails():
    class Broken:
        def search(self, *a, **k):
            raise ConnectionError("qdrant down")

    doc = make_doc("mh1", "MH", ["शेतकरी अनुदान योजना"])
    hybrid = HybridIndex(BM25Index(doc.to_passages()), Broken(), "MH", "mh1")
    hits = hybrid.search("अनुदान", k=3)
    assert hybrid.last_mode == "bm25" and hits[0].passage.passage_id == "mh1:p1:1"
