#!/usr/bin/env bash
# Record the three regional demo videos from the running app (run_app.sh).
# Optional: data/demo/questions/<STATE>.wav = consented recording of a real person asking the question.
set -euo pipefail
cd "$(dirname "$0")/../.."
for STATE in MH MP OD; do
  QA=()
  [[ -f "data/demo/questions/$STATE.wav" ]] && QA=(--question-audio "data/demo/questions/$STATE.wav")
  python scripts/demo/make_demo_video.py --state "$STATE" --base-url "http://127.0.0.1:${PORT:-8000}" "${QA[@]}"
done
ls -lh output/demo/*/
