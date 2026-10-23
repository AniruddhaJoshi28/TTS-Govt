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

port_free() { "$VENV_APP/bin/python" -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1])))' "$1" 2>/dev/null; }
next_free_port() { local p; for p in $(seq "$1" $(($1 + 100))); do port_free "$p" && { echo "$p"; return; }; done; return 1; }
step "Model server (SLM)"
show_gpu_plan
# One launcher for vLLM (also used by the app's supervisor): reuses a running server, otherwise
# starts one on a free port with the free-memory plan from env.sh.
SLM_OUT="$(bash "$(dirname "$0")/start_slm.sh")" || exit 1
read -r SLM_STATE LLM_PORT SLM_MODEL <<<"$SLM_OUT"
export LLM_PORT LLM_BASE_URL="http://127.0.0.1:$LLM_PORT/v1"
echo "SLM $SLM_STATE: $SLM_MODEL on port $LLM_PORT"
wait_for "$LLM_BASE_URL/models" 1800 vllm "$LOGS/vllm.log"

step "Building the corpus from the official sources (download + OCR)"
"$VENV_APP/bin/python" scripts/build_corpus.py --download || { echo "Corpus build failed; see the errors above." >&2; exit 1; }

step "Starting the application (it brings up the speech service: TTS=$TTS_ENGINE, STT=$STT_ENGINE on GPU $APP_GPUS)"
# Always (re)start the app: it loads the corpus at startup, and the corpus was just rebuilt.
if [[ -f "$LOGS/app.pid" ]] && kill -0 "$(cat "$LOGS/app.pid")" 2>/dev/null; then
  echo "restarting the running app so it loads the rebuilt corpus"
  kill "$(cat "$LOGS/app.pid")"
  for _ in $(seq 1 30); do kill -0 "$(cat "$LOGS/app.pid")" 2>/dev/null || break; sleep 1; done
fi
if ! port_free "$PORT"; then
  p="$(next_free_port $((PORT + 1)))" || { echo "no free port near $PORT" >&2; exit 1; }
  echo "port $PORT is used by another process; the app will use $p"
  export PORT="$p"
fi
echo "$PORT" >"$LOGS/app.port"
nohup "$VENV_APP/bin/python" -m uvicorn apps.api.main:app \
  --host 127.0.0.1 --port "$PORT" >"$LOGS/app.log" 2>&1 &
echo $! >"$LOGS/app.pid"
wait_for "http://127.0.0.1:$PORT/api/v1/health" 1800 app "$LOGS/app.log"

step "Health check (waits while the speech models load)"
"$VENV_APP/bin/python" - "$PORT" <<'EOF'
import json, sys, time, urllib.request
url = f"http://127.0.0.1:{sys.argv[1]}/api/v1/health"
deadline = time.time() + 1800
while True:
    data = json.load(urllib.request.urlopen(url))["data"]
    loading = [d["name"] for d in data["dependencies"] if d["status"] == "starting"]
    if not loading or time.time() > deadline:
        break
    print(f"  still loading: {', '.join(loading)} …", flush=True)
    time.sleep(10)
bad = []
for d in data["dependencies"]:
    print(f"  {d['name']:7s} {d['status']:15s} {d.get('detail') or ''}")
    if d["status"] != "ok":
        bad.append(d["name"])
optional = {
    "stt": "voice input (STT) is not loaded; the UI will ask users to type. "
           "Videos can still be recorded without --question-audio.",
    "qdrant": "vector search (Qdrant) is off; Q&A uses keyword search only. "
              "Install: uv pip install --python .venvs/app/bin/python 'qdrant-client>=1.14,<1.16' "
              "'fastembed-gpu>=0.8,<0.9', then re-run this script.",
}
for name in [b for b in bad if b in optional]:
    print(f"\nWarning: {optional[name]} See logs/app.log.")
bad = [b for b in bad if b not in optional]
if bad:
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
