from datetime import datetime, timedelta, timezone

import pytest

from services.document_ingestion.store import DocumentStore

URL = "https://gr.example.gov.in/a.pdf"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = DocumentStore(tmp_path)
    yield s
    s.close()


def test_new_then_unchanged(store):
    assert store.ingest("src", URL, b"v1", now=T0).status == "new"
    assert store.ingest("src", URL, b"v1", now=T0 + timedelta(days=1)).status == "unchanged"
    (only,) = store.versions(URL)
    assert only["last_checked_at"] == (T0 + timedelta(days=1)).isoformat()


def test_blob_is_stored_by_hash(store):
    r = store.ingest("src", URL, b"original bytes")
    assert store.read_blob(r.sha256) == b"original bytes"


def test_empty_content_is_rejected(store):
    with pytest.raises(ValueError):
        store.ingest("src", URL, b"")


def test_retry_backoff_grows_and_success_clears_queue(store):
    store.record_failure("src", URL, "timeout", now=T0)
    assert store.due_retries("src", now=T0) == []
    assert store.due_retries("src", now=T0 + timedelta(minutes=15)) == [URL]
    store.record_failure("src", URL, "timeout", now=T0)
    assert store.due_retries("src", now=T0 + timedelta(minutes=15)) == []
    assert store.due_retries("src", now=T0 + timedelta(minutes=30)) == [URL]
    store.ingest("src", URL, b"v1")
    assert store.due_retries("src", now=T0 + timedelta(days=2)) == []


def test_non_retryable_failure_is_logged_but_not_queued(store):
    store.record_failure("src", URL, "HTTP 404", retryable=False, now=T0)
    assert store.due_retries("src", now=T0 + timedelta(days=2)) == []
