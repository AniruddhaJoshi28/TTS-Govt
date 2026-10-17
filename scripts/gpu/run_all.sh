#!/usr/bin/env bash
# Start everything and record the three demo videos.
#
#   bash scripts/gpu/run_all.sh            # start services, build corpus, record videos
#   bash scripts/gpu/run_all.sh --serve    # start services only (use the UI, then record later)
#   bash scripts/gpu/stop_all.sh           # stop the services
#
# Logs: logs/vllm.log, logs/app.log. Videos: output/demo/<STATE>/.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
mkdir -p "$LOGS"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
wait_for() {  # url, seconds, name, logfile
  local url="$1" secs="$2" name="$3" log="$4"
  for ((i = 0; i < secs; i += 5)); do
    curl -fsS -o /dev/null "$url" 2>/dev/null && { echo "$name is up"; return 0; }
    if [[ -f "$LOGS/$name.pid" ]] && ! kill -0 "$(cat "$LOGS/$name.pid")" 2>/dev/null; then
      echo "$name exited during startup. Error lines from $log:" >&2
      grep -E "Error|ERROR|error:|out of memory|OutOfMemory|CUDA|insufficient|Free memory|not enough" "$log"         | grep -vE '^[[:space:]]+(File |\^|return |raise |with |async |self\.)' | tail -20 >&2
      echo "(Full log: $log. Send it if the cause is not clear.)" >&2
      return 1
    fi
    sleep 5
  done
  echo "$name did not start within ${secs}s; see $log" >&2; return 1
}

[[ -x "$VENV_APP/bin/python" && -x "$VENV_VLLM/bin/vllm" ]] || { echo "Run scripts/gpu/setup.sh first." >&2; exit 1; }

served_model() {  # the model id the running vLLM serves, or nothing
  curl -fsS "$LLM_BASE_URL/models" 2>/dev/null \
    | "$VENV_APP/bin/python" -c 'import json, sys; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null
}

RUNNING_MODEL="$(served_model || true)"
if [[ -n "$RUNNING_MODEL" ]]; then
  # A previous run's vLLM is still up. Its own memory shows as "used" in nvidia-smi, so the
  # free-memory plan is meaningless now: reuse the server and the model it actually serves.
  step "Model server already running: $RUNNING_MODEL"
  if [[ "$RUNNING_MODEL" != "$LLM_MODEL" ]]; then
    echo "using the running model $RUNNING_MODEL (a fresh start would have chosen $LLM_MODEL)"
  fi
  export LLM_MODEL="$RUNNING_MODEL"
  echo "Speech will run on GPU $APP_GPUS. To re-plan from scratch: bash scripts/gpu/stop_all.sh, then run this again."
else
  step "Checking GPU memory"
  show_gpu_plan
  if (( LLM_FREE_MB < 10000 )) && [[ -z "${GPU_MEM_OVERRIDE:-}" ]]; then
    echo "Not enough free GPU memory for the model right now (other jobs are using the GPUs)." >&2
    echo "Check with: nvidia-smi. Retry when memory frees up, or force a choice in .env:" >&2
    echo "  GPU_MEM_OVERRIDE=1  LLM_GPUS=<index>  GPU_MEM=<fraction>  LLM_MODEL=Qwen/Qwen3-4B" >&2
    exit 1
  fi

  step "Starting the model server: $LLM_MODEL (GPU $LLM_GPUS)"
  nohup "${VLLM_ENV[@]}" CUDA_VISIBLE_DEVICES="$LLM_GPUS" "$VENV_VLLM/bin/vllm" serve "$LLM_MODEL" --port "$LLM_PORT" \
    --dtype bfloat16 --max-model-len "$MAX_MODEL_LEN" --gpu-memory-utilization "$GPU_MEM" \
    --served-model-name "$LLM_MODEL" >"$LOGS/vllm.log" 2>&1 &
  echo $! >"$LOGS/vllm.pid"
  wait_for "$LLM_BASE_URL/models" 1800 vllm "$LOGS/vllm.log"
fi

step "Building the corpus from the official sources (download + OCR)"
"$VENV_APP/bin/python" scripts/build_corpus.py --download || { echo "Corpus build failed; see the errors above." >&2; exit 1; }

step "Starting the application with TTS=$TTS_ENGINE, STT=$STT_ENGINE (GPU $APP_GPUS)"
# Always (re)start the app: it loads the corpus at startup, and the corpus was just rebuilt.
if [[ -f "$LOGS/app.pid" ]] && kill -0 "$(cat "$LOGS/app.pid")" 2>/dev/null; then
  echo "restarting the running app so it loads the rebuilt corpus"
  kill "$(cat "$LOGS/app.pid")"
  for _ in $(seq 1 30); do kill -0 "$(cat "$LOGS/app.pid")" 2>/dev/null || break; sleep 1; done
fi
if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/v1/health" 2>/dev/null; then
  echo "Port $PORT is still in use by another process (not started by this script). Stop it or set PORT in .env." >&2
  exit 1
fi
CUDA_VISIBLE_DEVICES="$APP_GPUS" nohup "$VENV_APP/bin/python" -m uvicorn apps.api.main:app \
  --host 127.0.0.1 --port "$PORT" >"$LOGS/app.log" 2>&1 &
echo $! >"$LOGS/app.pid"
wait_for "http://127.0.0.1:$PORT/api/v1/health" 1800 app "$LOGS/app.log"

step "Health check"
"$VENV_APP/bin/python" - "$PORT" <<'EOF'
import json, sys, urllib.request
data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/v1/health"))["data"]
bad = []
for d in data["dependencies"]:
    print(f"  {d['name']:7s} {d['status']:15s} {d.get('detail') or ''}")
    if d["status"] != "ok":
        bad.append(d["name"])
if bad == ["stt"]:
    print("\nWarning: voice input (STT) is not loaded; the UI will ask users to type. "
          "Videos can still be recorded without --question-audio. See logs/app.log.")
elif bad:
    print(f"\nNot ready: {', '.join(bad)}. Check logs/app.log and logs/vllm.log.", file=sys.stderr)
    sys.exit(1)
EOF

echo
echo "UI: http://127.0.0.1:$PORT  (from your laptop: ssh -L $PORT:127.0.0.1:$PORT <user>@<server>, then open http://localhost:$PORT)"

if [[ "${1:-}" == "--serve" ]]; then
  echo "Services running. Record later with: bash scripts/gpu/make_all_videos.sh"
  exit 0
fi

step "Recording demo videos (MH, MP, OD)"
bash scripts/gpu/make_all_videos.sh
echo
echo "Done. Review every video and its evidence.json before sharing (docs/demo_scripts/README.md)."
echo "Services are still running; stop them with: bash scripts/gpu/stop_all.sh"
