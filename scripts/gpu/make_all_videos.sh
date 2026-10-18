#!/usr/bin/env bash
# Record the three regional demo videos from the running app.
# Optional: data/demo/questions/<STATE>.wav = consented recording of a real person asking the scene question.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
failed=()
for STATE in MH MP OD; do
  QA=()
  [[ -f "data/demo/questions/$STATE.wav" ]] && QA=(--question-audio "data/demo/questions/$STATE.wav")
  if ! "$VENV_APP/bin/python" scripts/demo/make_demo_video.py --state "$STATE" \
       --base-url "http://127.0.0.1:$PORT" ${API_KEY:+--api-key "$API_KEY"} ${QA[@]+"${QA[@]}"}; then
    failed+=("$STATE")
  fi
done
echo
echo "Finished videos:"
ls -lh output/demo/final/*.mp4 2>/dev/null || echo "  (none)"
if (( ${#failed[@]} > 0 )); then
  echo "Not recorded: ${failed[*]} (see the ABORTED reason above)." >&2
  exit 1
fi
