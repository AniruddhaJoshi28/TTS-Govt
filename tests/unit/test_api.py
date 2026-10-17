import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_health_reports_degraded_until_dependencies_configured():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "degraded"
    assert body["error"] is None
    assert {d["status"] for d in body["data"]["dependencies"]} == {"not_configured"}


def test_request_id_is_echoed_when_valid():
    rid = str(uuid.uuid4())
    resp = client.get("/api/v1/health", headers={"X-Request-ID": rid})
    assert resp.headers["X-Request-ID"] == rid
    assert resp.json()["request_id"] == rid


def test_invalid_request_id_is_replaced():
    resp = client.get("/api/v1/health", headers={"X-Request-ID": "<script>"})
    uuid.UUID(resp.headers["X-Request-ID"])


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/documents"),
        ("GET", "/api/v1/documents/abc"),
        ("POST", "/api/v1/summaries"),
        ("POST", "/api/v1/qa"),
        ("POST", "/api/v1/speech/transcriptions"),
        ("POST", "/api/v1/speech/synthesis"),
        ("GET", "/api/v1/audio-assets/abc"),
        ("POST", "/api/v1/feedback"),
    ],
)
def test_planned_endpoints_fail_explicitly(method, path):
    resp = client.request(method, path)
    assert resp.status_code == 501
    body = resp.json()
    assert body["error"]["code"] == "not_implemented"
    assert body["data"] is None
    assert body["sources"] == []
