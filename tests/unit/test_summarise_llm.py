import json

import pytest
import requests

from schemas.api.envelope import Language
from services.slm_orchestrator.llm import LLMConfig, LLMUnavailable, OpenAICompatibleLLM
from services.slm_orchestrator.summarise import summarise
from tests.helpers import passage

P1 = passage("p1", "सर्व खाजगी रुग्णालयांनी सेवा आणि सुविधांचे दर ठळकपणे प्रदर्शित करावेत.")
P2 = passage("p2", "सदर दरांची यादी मराठी आणि इंग्रजी या दोन्ही भाषांमध्ये असणे अनिवार्य आहे. दिनांक १६.१०.२०२६")


def model_reply(sections, uncertainties=()):
    return json.dumps({"sections": {k: [{"text": t, "citations": c} for t, c in v] for k, v in sections.items()},
                       "uncertainties": list(uncertainties)}, ensure_ascii=False)


def test_summary_keeps_supported_and_marks_missing_sections():
    raw = model_reply({
        "what": [("खाजगी रुग्णालयांनी दर ठळकपणे लावावेत.", ["p1"])],
        "conditions": [("दरांची यादी मराठी आणि इंग्रजीत असावी.", ["p2"])],
        "dates": [("परिपत्रक दिनांक 16.10.2026 चे आहे.", ["p2"])],
    })
    r = summarise([P1, P2], Language.MARATHI, lambda _: raw)
    by_key = {s.key: s for s in r.sections}
    assert r.status == "summarised"
    assert by_key["what"].status == "stated"
    assert by_key["dates"].status == "stated"  # Devanagari digits in source match ASCII in claim
    assert by_key["eligibility"].status == "not_stated"
    assert {p.passage_id for p in r.sources} == {"p1", "p2"}


def test_invented_deadline_is_removed():
    raw = model_reply({"dates": [("अंतिम तारीख 30.11.2026 आहे.", ["p2"])]})
    r = summarise([P1, P2], Language.MARATHI, lambda _: raw)
    assert {s.key: s.status for s in r.sections}["dates"] == "not_stated"
    assert r.rejected and r.uncertainties


def test_fenced_json_is_accepted_and_prose_retried():
    replies = iter(["Here you go!", "```json\n" + model_reply({"what": [("दर लावावेत.", ["p1"])]}) + "\n```"])
    r = summarise([P1], Language.MARATHI, lambda _: next(replies))
    assert r.status == "summarised"


def test_summary_fails_safely_after_bounded_retries():
    calls = []
    r = summarise([P1], Language.MARATHI, lambda p: calls.append(p) or "not json")
    assert r.status == "failed" and len(calls) == 3 and not r.sections


class FakeHTTP:
    def __init__(self, status=200, payload=None, exc=None):
        self.status, self.payload, self.exc, self.sent = status, payload, exc, None

    def post(self, url, json=None, timeout=None, headers=None):
        self.sent = (url, json)
        if self.exc:
            raise self.exc
        resp = type("R", (), {})()
        resp.status_code = self.status
        resp.json = lambda: self.payload
        return resp


def test_llm_adapter_sends_openai_request_and_strips_thinking():
    http = FakeHTTP(payload={"choices": [{"message": {"content": "<think>hmm</think>{\"claims\": []}"}}]})
    llm = OpenAICompatibleLLM(LLMConfig(base_url="http://gpu:8000/v1"), session=http)
    assert llm("prompt") == '{"claims": []}'
    url, body = http.sent
    assert url == "http://gpu:8000/v1/chat/completions"
    assert body["model"] == "Qwen/Qwen3-8B" and body["response_format"] == {"type": "json_object"}
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("http", [FakeHTTP(exc=requests.ConnectionError("down")), FakeHTTP(status=503), FakeHTTP(payload={})])
def test_llm_adapter_failures_are_explicit(http):
    with pytest.raises(LLMUnavailable):
        OpenAICompatibleLLM(LLMConfig(base_url="http://gpu:8000/v1"), session=http)("prompt")


def test_llm_config_from_env(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert LLMConfig.from_env() is None
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu:8000/v1/")
    monkeypatch.setenv("LLM_MODEL", "sarvamai/sarvam-m")
    c = LLMConfig.from_env()
    assert c.base_url == "http://gpu:8000/v1" and c.model == "sarvamai/sarvam-m"
