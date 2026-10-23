#!/usr/bin/env bash
# Stop the app, the speech service and the SLM server (started by run_all.sh or by the app supervisor).
source "$(dirname "$0")/env.sh"
for name in app speech vllm; do
  pidfile="$LOGS/$name.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")" && echo "stopped $name"
  fi
  rm -f "$pidfile"
done
rm -f "$LOGS/vllm.port" "$LOGS/app.port" "$LOGS/speech.port"
