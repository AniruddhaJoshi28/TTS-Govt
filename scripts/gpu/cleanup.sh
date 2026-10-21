#!/usr/bin/env bash
# Free GPU memory, RAM and disk used by this project on a shared server.
#
#   bash scripts/gpu/cleanup.sh                 # REPORT ONLY: what uses GPU/disk, what would be removed
#   bash scripts/gpu/cleanup.sh --gpu           # stop YOUR stale vLLM / uvicorn / python GPU processes
#   bash scripts/gpu/cleanup.sh --models --yes  # delete downloaded models this app does not use
#   bash scripts/gpu/cleanup.sh --caches --yes  # delete pip/uv/old embedding caches
#   bash scripts/gpu/cleanup.sh --all --yes     # all of the above
#
# Only your own processes and files are touched. Models in use are always kept:
#   $LLM_MODEL (from .env), ai4bharat/* (TTS, STT), google/flan-t5* (Parler text encoder),
#   parler-tts/*, intfloat/* + qdrant/* (embeddings). Add more with KEEP_MODELS="org/a org/b".
set -uo pipefail
cd "$(dirname "$0")/../.."
[[ -f .env ]] && set -a && source .env && set +a

DO_GPU=0 DO_MODELS=0 DO_CACHES=0 YES=0
for a in "$@"; do
  case "$a" in
    --gpu) DO_GPU=1 ;; --models) DO_MODELS=1 ;; --caches) DO_CACHES=1 ;;
    --all) DO_GPU=1 DO_MODELS=1 DO_CACHES=1 ;; --yes|-y) YES=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

HUB="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
KEEP=("${LLM_MODEL:-Qwen/Qwen3-4B}" "ai4bharat/*" "google/flan-t5*" "parler-tts/*" "intfloat/*" "qdrant/*" ${KEEP_MODELS:-})
hr() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
keep() { local m="$1" k; for k in "${KEEP[@]}"; do [[ "$m" == $k ]] && return 0; done; return 1; }

# ---------------------------------------------------------------- GPU
hr "GPU memory"
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
  echo "-- processes on the GPU (all users):"
  nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader | while IFS=, read -r pid mem name; do
    owner=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
    printf '  pid %-8s %-10s %-12s %s\n' "$pid" "$mem" "${owner:-?}" "$(ps -o args= -p "$pid" 2>/dev/null | cut -c1-90)"
  done
else
  echo "nvidia-smi not found"
fi
MINE=$(pgrep -u "$USER" -f 'vllm serve|uvicorn apps.api.main|multiprocessing.spawn|VLLM::' || true)
if [[ -n "$MINE" ]]; then
  echo "-- your project processes: $(echo $MINE)"
  if (( DO_GPU )); then
    bash scripts/gpu/stop_all.sh 2>/dev/null || true
    kill $MINE 2>/dev/null; sleep 5
    STILL=$(pgrep -u "$USER" -f 'vllm serve|uvicorn apps.api.main|multiprocessing.spawn|VLLM::' || true)
    [[ -n "$STILL" ]] && kill -9 $STILL 2>/dev/null
    echo "stopped. GPU now:"; nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null
  else
    echo "   (run with --gpu to stop them)"
  fi
else
  echo "-- no project processes of yours are running"
fi

# ---------------------------------------------------------------- models
hr "Downloaded models ($HUB)"
TO_DELETE=()
if [[ -d "$HUB" ]]; then
  for d in "$HUB"/models--*; do
    [[ -d "$d" ]] || continue
    name=$(basename "$d" | sed 's/^models--//; s/--/\//')
    size=$(du -sh "$d" 2>/dev/null | cut -f1)
    if keep "$name"; then printf '  keep    %-8s %s\n' "$size" "$name"
    else printf '  REMOVE  %-8s %s\n' "$size" "$name"; TO_DELETE+=("$d"); fi
  done
else
  echo "  (no Hugging Face cache)"
fi
if (( DO_MODELS )) && (( ${#TO_DELETE[@]} )); then
  if (( YES )); then rm -rf "${TO_DELETE[@]}" && echo "removed ${#TO_DELETE[@]} model(s)"
  else echo "add --yes to delete the ${#TO_DELETE[@]} model(s) marked REMOVE"; fi
elif (( ${#TO_DELETE[@]} )); then
  echo "   (run with --models --yes to delete the ones marked REMOVE)"
fi

# ---------------------------------------------------------------- caches
hr "Caches"
CACHES=(/tmp/fastembed_cache "$HOME/.cache/pip" "$HOME/.cache/uv")
for c in "${CACHES[@]}"; do [[ -e "$c" ]] && printf '  %-8s %s\n' "$(du -sh "$c" 2>/dev/null | cut -f1)" "$c"; done
if (( DO_CACHES )); then
  if (( YES )); then
    # /tmp/fastembed_cache is the old symlinked embedding cache; models now live in ~/.cache/gr-embeddings.
    rm -rf /tmp/fastembed_cache "$HOME/.cache/pip"
    command -v uv >/dev/null && uv cache clean >/dev/null 2>&1 || rm -rf "$HOME/.cache/uv"
    echo "caches cleared"
  else echo "add --yes to clear these caches"; fi
fi

hr "Disk"
df -h "$HOME" | tail -1
