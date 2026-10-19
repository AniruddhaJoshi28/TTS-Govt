"""Model adapter for any OpenAI-compatible chat endpoint (vLLM, Ollama, llama.cpp).

The application only depends on ``generate(prompt) -> str``; swapping Qwen3-8B
for another model is a configuration change (LLM_MODEL), not a code change.
"""

import os
import re
import sys
import time

import requests
from pydantic import BaseModel

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe = [a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a for a in args]
        print(*safe, **kwargs)


DEFAULT_MODEL = "Qwen/Qwen3-8B"

SYSTEM = (
    "You are a careful assistant that explains Indian government documents to citizens. "
    "You only state what the provided passages say, and you always reply with a single JSON object."
)


class LLMUnavailable(RuntimeError):
    pass


class LLMConfig(BaseModel):
    base_url: str
    model: str = DEFAULT_MODEL
    api_key: str = "EMPTY"
    temperature: float = 0.1
    max_tokens: int = 4096  # Indic scripts use many tokens per word
    timeout: float = 300.0
    # Qwen3: disable the reasoning trace so the reply is the JSON object only.
    extra_body: dict = {"chat_template_kwargs": {"enable_thinking": False}}

    @classmethod
    def from_env(cls) -> "LLMConfig | None":
        base = os.environ.get("LLM_BASE_URL")
        if not base:
            return None
        return cls(base_url=base.rstrip("/"), model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
                   api_key=os.environ.get("LLM_API_KEY", "EMPTY"))


import time

class OpenAICompatibleLLM:
    def __init__(self, config: LLMConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()

    @property
    def model(self) -> str:
        return self.config.model

    def __call__(self, prompt: str) -> str:
        c = self.config
        body = {
            "model": c.model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "temperature": c.temperature,
            "max_tokens": c.max_tokens,
            "response_format": {"type": "json_object"},
            **c.extra_body,
        }
        _safe_print(f"\n{'-'*65}")
        _safe_print(f"🤖 [SLM INVOCATION] Sending request to SLM: '{c.model}'")
        _safe_print(f"   • Endpoint: {c.base_url}/chat/completions")
        _safe_print(f"   • Temperature: {c.temperature} | Max tokens: {c.max_tokens}")
        _safe_print(f"   • Prompt size: {len(prompt):,} characters")

        start_t = time.perf_counter()
        try:
            resp = self.session.post(f"{c.base_url}/chat/completions", json=body, timeout=c.timeout,
                                     headers={"Authorization": f"Bearer {c.api_key}"})
        except requests.RequestException as exc:
            _safe_print(f"❌ [SLM ERROR] Server unreachable: {exc}")
            raise LLMUnavailable(f"model server unreachable: {type(exc).__name__}") from exc

        elapsed = time.perf_counter() - start_t

        if resp.status_code != 200:
            err_text = getattr(resp, "text", "")[:200]
            _safe_print(f"❌ [SLM ERROR] HTTP {resp.status_code}: {err_text}")
            raise LLMUnavailable(f"model server returned HTTP {resp.status_code}")

        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError) as exc:
            _safe_print(f"❌ [SLM ERROR] Malformed response payload: {exc}")
            raise LLMUnavailable("model server returned an unexpected response") from exc

        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        preview = (cleaned[:160] + "...") if len(cleaned) > 160 else cleaned
        _safe_print(f"🤖 [SLM RESPONSE RECEIVED] Completed in {elapsed:.2f}s ({len(cleaned):,} characters)")
        _safe_print(f"   • JSON Output Preview: {preview}")
        _safe_print(f"{'-'*65}\n")
        return cleaned
