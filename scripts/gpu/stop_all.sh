#!/usr/bin/env bash
# Stop the services started by run_all.sh.
source "$(dirname "$0")/env.sh"
for name in app vllm; do
  pidfile="$LOGS/$name.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    kill "$(cat "$pidfile")" && echo "stopped $name"
  fi
  rm -f "$pidfile"
done
