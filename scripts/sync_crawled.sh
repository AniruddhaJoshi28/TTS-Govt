#!/usr/bin/env bash
# Crawl the official portals, import new GRs into the assistant corpus (OCR where the text layer
# is broken), and make the running app pick them up (BM25 + Qdrant GOVT_<STATE> collections).
#
#   bash scripts/sync_crawled.sh                 # incremental crawl of all active sources
#   PAGES=5 DOWNLOADS=50 bash scripts/sync_crawled.sh
#
# Schedule it, e.g. every 3 hours:   crontab -e
#   0 */3 * * * cd $HOME/AJ_WORK/TTS-SLM/TTS-Govt && bash scripts/sync_crawled.sh >> logs/sync.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
[[ -f .env ]] && set -a && source .env && set +a

PAGES="${PAGES:-2}"
DOWNLOADS="${DOWNLOADS:-30}"
# run_all.sh records the port it actually used (it moves off ports taken by other users).
[[ -f logs/app.port ]] && PORT="$(cat logs/app.port)"
APP_URL="${APP_URL:-http://127.0.0.1:${PORT:-8000}}"
first_python() { for p in "$@"; do [[ -x "$p" ]] && { echo "$p"; return; }; done; command -v python; }
APP_PY="${APP_PY:-$(first_python "$ROOT/.venvs/app/bin/python" "$ROOT/.venv/bin/python")}"
PLATFORM_PY="${PLATFORM_PY:-$(first_python "$ROOT/government-gr-platform/.venv/bin/python" "$ROOT/.venv/bin/python")}"
# OCR tools installed without root (see government-gr-platform docs): keep them after the venv on PATH.
[[ -d "$HOME/ocr-env/bin" ]] && export PATH="$PATH:$HOME/ocr-env/bin"
[[ -d "$HOME/tessdata" ]] && export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$HOME/tessdata}"

echo "== $(date -Is) crawl (pages=$PAGES, downloads/source=$DOWNLOADS)"
(cd government-gr-platform && "$PLATFORM_PY" -m apps.crawler.cli crawl-active --max-pages "$PAGES" --download-limit "$DOWNLOADS")

echo "== import into corpus"
RELOAD=()
curl -fsS -o /dev/null "$APP_URL/api/v1/health" 2>/dev/null && RELOAD=(--reload-url "$APP_URL/api/v1/reload" --warm-url "$APP_URL")
"$APP_PY" scripts/import_crawled.py "${RELOAD[@]}"
[[ ${#RELOAD[@]} -eq 0 ]] && echo "(app not running at $APP_URL; it will load the new documents on its next start)"
echo "== done"
