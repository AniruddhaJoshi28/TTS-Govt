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

# vLLM's FlashInfer sampler JIT-compiles a kernel with nvcc at startup. Shared servers often
# have an older system CUDA (/usr/local/cuda) whose nvcc rejects FlashInfer's flags
# ("Unknown option '--compress-mode=size'"). Use vLLM's PyTorch sampler instead (no compiling),
# and if anything else must compile, prefer the newer nvcc installed inside the vLLM env.
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
VLLM_CUDA_HOME=""
for nvcc in "$VENV_VLLM"/lib/python3*/site-packages/nvidia/*/bin/nvcc "$VENV_VLLM"/lib/python3*/site-packages/nvidia/cuda_nvcc/bin/nvcc; do
  root="$(dirname "$(dirname "$nvcc")")"
  if [[ -x "$nvcc" && -f "$root/include/cuda_runtime.h" ]]; then
    VLLM_CUDA_HOME="$root"
    break
  fi
done
export VLLM_CUDA_HOME

# Command prefix for the vLLM process only (the app environment never compiles CUDA code).
# An array, not a function, so `nohup "${VLLM_ENV[@]}" vllm ... &` records vLLM's own PID.
VLLM_ENV=(env)
if [[ -n "$VLLM_CUDA_HOME" ]]; then
  VLLM_ENV+=(CUDA_HOME="$VLLM_CUDA_HOME" PATH="$VLLM_CUDA_HOME/bin:$PATH")
fi

export LLM_PORT="${LLM_PORT:-8001}"
export PORT="${PORT:-8000}"
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:$LLM_PORT/v1}"
export TTS_ENGINE="${TTS_ENGINE:-parler}"
export STT_ENGINE="${STT_ENGINE:-indicconformer}"

# GPU layout. Two or more GPUs: model on GPU 0, speech on GPU 1.
# The choice uses memory that is FREE right now, because shared servers run other
# people's jobs: vLLM refuses to start if (GPU_MEM x total) is more than what is free.
#   - the model goes on the GPU with the most free memory;
#   - speech (~8 GB) goes on the next GPU if it has room, otherwise shares;
#   - GPU_MEM is sized to the free memory; the model shrinks if memory is short.
GPU_COUNT=0
GPU_TABLE=""
if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_TABLE="$(nvidia-smi --query-gpu=index,memory.total,memory.free --format=csv,noheader,nounits \
    | tr -d ' ' | sort -t, -k3 -nr)"
  GPU_COUNT="$(grep -c . <<<"$GPU_TABLE" || true)"
fi
export GPU_COUNT GPU_TABLE
LLM_FREE_MB=0
if (( GPU_COUNT > 0 )); then
  IFS=, read -r B_IDX B_TOT B_FREE <<<"$(sed -n 1p <<<"$GPU_TABLE")"
  APP_DEFAULT="$B_IDX"
  RESERVE=8192
  if (( GPU_COUNT >= 2 )); then
    IFS=, read -r S_IDX S_TOT S_FREE <<<"$(sed -n 2p <<<"$GPU_TABLE")"
    if (( S_FREE >= 9000 )); then APP_DEFAULT="$S_IDX"; RESERVE=0; fi
  fi
  LLM_FREE_MB=$(( B_FREE - RESERVE - 1536 ))
  FRACTION="$(awk -v u="$LLM_FREE_MB" -v t="$B_TOT" 'BEGIN { f = u / t; if (f > 0.90) f = 0.90; if (f < 0) f = 0; printf "%.2f", f }')"
  if (( LLM_FREE_MB >= 24000 )); then
    MODEL_DEFAULT="Qwen/Qwen3-8B"; LEN_DEFAULT=32768
  elif (( LLM_FREE_MB >= 19000 )); then
    MODEL_DEFAULT="Qwen/Qwen3-8B"; LEN_DEFAULT=16384
  else
    MODEL_DEFAULT="Qwen/Qwen3-4B"; LEN_DEFAULT=16384
  fi
  export LLM_GPUS="${LLM_GPUS:-$B_IDX}" APP_GPUS="${APP_GPUS:-$APP_DEFAULT}"
  export GPU_MEM="${GPU_MEM:-$FRACTION}"
  export LLM_MODEL="${LLM_MODEL:-$MODEL_DEFAULT}" MAX_MODEL_LEN="${MAX_MODEL_LEN:-$LEN_DEFAULT}"
fi
export LLM_FREE_MB

show_gpu_plan() {
  echo "GPU memory right now (index, total MB, free MB):"
  sed 's/^/  /' <<<"$GPU_TABLE"
  echo "Plan: $LLM_MODEL on GPU $LLM_GPUS (GPU_MEM=$GPU_MEM, context $MAX_MODEL_LEN), speech on GPU $APP_GPUS"
  echo "vLLM: FlashInfer sampler $([[ $VLLM_USE_FLASHINFER_SAMPLER == 0 ]] && echo off || echo on);"        "CUDA compiler: ${VLLM_CUDA_HOME:-system (/usr/local/cuda)}"
}

# Offline model loading. When a model is already in the Hugging Face cache, services start with
# HF_HUB_OFFLINE=1 so they never contact huggingface.co: on networks whose proxy blocks it
# ("403 Forbidden" / ProxyError) an online lookup would make vLLM or the TTS fail at startup.
# HF_OFFLINE=1 forces offline, HF_OFFLINE=0 forces online (e.g. to download a new model).
HF_HUB_DIR="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
hf_cached() {  # repo id (org/name) -> true if a downloaded snapshot exists
  compgen -G "$HF_HUB_DIR/models--${1//\//--}/snapshots/*/config.json" >/dev/null 2>&1 \
    || compgen -G "$HF_HUB_DIR/models--${1//\//--}/snapshots/*/*" >/dev/null 2>&1
}
use_offline_if_cached() {  # repo ids...
  case "${HF_OFFLINE:-auto}" in
    1) export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1; return ;;
    0) return ;;
  esac
  local r; for r in "$@"; do hf_cached "$r" || return 0; done
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
}
