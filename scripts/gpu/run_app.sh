#!/usr/bin/env bash
# Build the corpus and run only the app (foreground). run_all.sh does this for you.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
"$VENV_APP/bin/python" scripts/build_corpus.py --download
CUDA_VISIBLE_DEVICES="$APP_GPUS" exec "$VENV_APP/bin/python" -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$PORT"
