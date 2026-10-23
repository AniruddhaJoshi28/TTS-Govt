#!/usr/bin/env bash
# Start the speech service (TTS + STT, apps/speech_service) if it is not already running.
# Idempotent and non-blocking: prints "running <port>" / "started <port>"; callers poll /health.
# GPU comes from env.sh (APP_GPUS: the GPU left after the SLM plan). Engines from TTS_ENGINE / STT_ENGINE.
# Logs: logs/speech.log   Port: logs/speech.port   PID: logs/speech.pid
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
mkdir -p "$LOGS"
PY="$VENV_APP/bin/python"; [[ -x "$PY" ]] || { echo "error app environment missing ($VENV_APP); run scripts/gpu/setup.sh" >&2; exit 1; }

port_free() { "$PY" -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1])))' "$1" 2>/dev/null; }
next_free_port() { local p; for p in $(seq "$1" $(($1 + 100))); do port_free "$p" && { echo "$p"; return; }; done; return 1; }

SPEECH_PORT="${SPEECH_PORT:-8100}"
[[ -f "$LOGS/speech.port" ]] && SPEECH_PORT="$(cat "$LOGS/speech.port")"
if curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$SPEECH_PORT/health" 2>/dev/null; then
  echo "running $SPEECH_PORT"; exit 0
fi
if [[ -f "$LOGS/speech.pid" ]] && kill -0 "$(cat "$LOGS/speech.pid")" 2>/dev/null; then
  echo "starting $SPEECH_PORT"; exit 0
fi
port_free "$SPEECH_PORT" || SPEECH_PORT="$(next_free_port $((SPEECH_PORT + 1)))"
echo "$SPEECH_PORT" >"$LOGS/speech.port"
CUDA_VISIBLE_DEVICES="${APP_GPUS:-0}" nohup "$PY" -m uvicorn apps.speech_service.main:app \
  --host 127.0.0.1 --port "$SPEECH_PORT" >"$LOGS/speech.log" 2>&1 &
echo $! >"$LOGS/speech.pid"
echo "started $SPEECH_PORT"
