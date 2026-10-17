#!/usr/bin/env bash
# Build the corpus and start the API + web UI with real speech models.
# Run inside the *app* environment (see docs/operations/gpu-server.md).
set -euo pipefail
cd "$(dirname "$0")/../.."
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:${LLM_PORT:-8001}/v1}"
export LLM_MODEL="${LLM_MODEL:-Qwen/Qwen3-8B}"
export TTS_ENGINE="${TTS_ENGINE:-parler}"
export STT_ENGINE="${STT_ENGINE:-indicconformer}"
python scripts/build_corpus.py --download
exec python -m uvicorn apps.api.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
