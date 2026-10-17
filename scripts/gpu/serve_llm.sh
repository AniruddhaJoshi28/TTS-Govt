#!/usr/bin/env bash
# Serve only the model (foreground). run_all.sh does this for you.
set -euo pipefail
source "$(dirname "$0")/env.sh"
CUDA_VISIBLE_DEVICES="$LLM_GPUS" exec "$VENV_VLLM/bin/vllm" serve "$LLM_MODEL" --port "$LLM_PORT" --dtype bfloat16 \
  --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_MEM" --served-model-name "$LLM_MODEL"
