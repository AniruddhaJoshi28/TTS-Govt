#!/usr/bin/env bash
# Serve the summarisation model with vLLM (OpenAI-compatible API on $LLM_PORT).
# Run inside the *vLLM* environment (see docs/operations/gpu-server.md).
set -euo pipefail
MODEL="${LLM_MODEL:-Qwen/Qwen3-8B}"
PORT="${LLM_PORT:-8001}"
# Leave GPU memory for TTS/STT when they share the card.
GPU_MEM="${GPU_MEM:-0.55}"
exec vllm serve "$MODEL" --port "$PORT" --dtype bfloat16 --max-model-len 32768 \
  --gpu-memory-utilization "$GPU_MEM" --served-model-name "$MODEL"
