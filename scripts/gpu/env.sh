#!/usr/bin/env bash
# Shared settings for the GPU scripts. Sourced by setup.sh, run_all.sh, serve_llm.sh and run_app.sh.
# Override anything by exporting it first or by putting it in .env at the repository root.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ROOT
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

export VENV_APP="${VENV_APP:-$ROOT/.venvs/app}"
export VENV_VLLM="${VENV_VLLM:-$ROOT/.venvs/vllm}"
export TOOLS="${TOOLS:-$ROOT/.tools}"
export LOGS="${LOGS:-$ROOT/logs}"
export PATH="$HOME/.local/bin:$TOOLS/bin:$PATH"

# OCR: use a system tesseract if present, otherwise the one setup.sh installed under .tools/.
if [[ -z "${TESSERACT_CMD:-}" ]]; then
  if [[ -x "$TOOLS/tess/bin/tesseract" ]]; then
    export TESSERACT_CMD="$TOOLS/tess/bin/tesseract"
  elif command -v tesseract >/dev/null 2>&1; then
    export TESSERACT_CMD="$(command -v tesseract)"
  fi
fi
# Language data (mar, hin, ori, eng from tessdata_best) always comes from .tools/tessdata.
export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$TOOLS/tessdata}"

export LLM_PORT="${LLM_PORT:-8001}"
export PORT="${PORT:-8000}"
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:$LLM_PORT/v1}"
export TTS_ENGINE="${TTS_ENGINE:-parler}"
export STT_ENGINE="${STT_ENGINE:-indicconformer}"

# GPU layout. Two or more GPUs: model on GPU 0, speech on GPU 1.
# One large GPU (>= 40 GB): share it. One smaller GPU: fall back to Qwen3-4B.
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_COUNT="$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)"
  GPU0_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')"
else
  GPU_COUNT=0
  GPU0_MB=0
fi
export GPU_COUNT GPU0_MB
if (( GPU_COUNT >= 2 )); then
  export LLM_GPUS="${LLM_GPUS:-0}" APP_GPUS="${APP_GPUS:-1}"
  export GPU_MEM="${GPU_MEM:-0.85}" MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
  export LLM_MODEL="${LLM_MODEL:-Qwen/Qwen3-8B}"
elif (( GPU0_MB >= 40000 )); then
  export LLM_GPUS="${LLM_GPUS:-0}" APP_GPUS="${APP_GPUS:-0}"
  export GPU_MEM="${GPU_MEM:-0.55}" MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
  export LLM_MODEL="${LLM_MODEL:-Qwen/Qwen3-8B}"
else
  export LLM_GPUS="${LLM_GPUS:-0}" APP_GPUS="${APP_GPUS:-0}"
  export GPU_MEM="${GPU_MEM:-0.60}" MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"
  export LLM_MODEL="${LLM_MODEL:-Qwen/Qwen3-4B}"
fi
