#!/usr/bin/env bash
# Start the SLM server (vLLM) if it is not already running. Idempotent and non-blocking:
# prints "running <port> <model>" or "started <port> <model>" and returns immediately; callers poll
# http://127.0.0.1:<port>/v1/models. Model, GPU and memory share come from env.sh (free-memory plan).
# Logs: logs/vllm.log   Port: logs/vllm.port   PID: logs/vllm.pid
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
mkdir -p "$LOGS"
[[ -x "$VENV_VLLM/bin/vllm" ]] || { echo "error vLLM not installed ($VENV_VLLM); run scripts/gpu/setup.sh" >&2; exit 1; }
PY="$VENV_APP/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"

port_free() { "$PY" -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1])))' "$1" 2>/dev/null; }
next_free_port() { local p; for p in $(seq "$1" $(($1 + 100))); do port_free "$p" && { echo "$p"; return; }; done; return 1; }
served_model() {
  curl -fsS -m 5 "http://127.0.0.1:$1/v1/models" 2>/dev/null \
    | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null
}

[[ -f "$LOGS/vllm.port" ]] && LLM_PORT="$(cat "$LOGS/vllm.port")"
if model="$(served_model "$LLM_PORT")" && [[ -n "$model" ]]; then
  echo "running $LLM_PORT $model"; exit 0
fi
# Still loading from an earlier start? Don't start a second copy.
if [[ -f "$LOGS/vllm.pid" ]] && kill -0 "$(cat "$LOGS/vllm.pid")" 2>/dev/null; then
  echo "starting $LLM_PORT $LLM_MODEL"; exit 0
fi

if (( LLM_FREE_MB < 10000 )) && [[ -z "${GPU_MEM_OVERRIDE:-}" ]]; then
  echo "error not enough free GPU memory for the model (${LLM_FREE_MB} MB usable); see nvidia-smi or set GPU_MEM_OVERRIDE=1" >&2
  exit 1
fi
port_free "$LLM_PORT" || LLM_PORT="$(next_free_port $((LLM_PORT + 1)))"
echo "$LLM_PORT" >"$LOGS/vllm.port"
use_offline_if_cached "$LLM_MODEL"
nohup "${VLLM_ENV[@]}" ${HF_HUB_OFFLINE:+HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1} CUDA_VISIBLE_DEVICES="$LLM_GPUS" "$VENV_VLLM/bin/vllm" serve "$LLM_MODEL" --port "$LLM_PORT" \
  --dtype bfloat16 --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_MEM" \
  --served-model-name "$LLM_MODEL" >"$LOGS/vllm.log" 2>&1 &
echo $! >"$LOGS/vllm.pid"
echo "started $LLM_PORT $LLM_MODEL${HF_HUB_OFFLINE:+ (offline: cached model)}"
