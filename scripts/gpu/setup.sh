#!/usr/bin/env bash
# One-time setup on a Linux GPU server. Safe to re-run; finished steps are skipped.
#
#   bash scripts/gpu/setup.sh
#
# Installs, without needing root:
#   - uv and Python 3.12
#   - .venvs/vllm : vLLM (serves the summarisation model)
#   - .venvs/app  : the application, Indic Parler-TTS, IndicConformer deps, Playwright Chromium
#   - Tesseract OCR (system package if available, otherwise from conda-forge into .tools/)
#   - Tesseract language data for Marathi, Hindi, Odia and English (tessdata_best)
#   - all model weights (Qwen, Indic Parler-TTS, IndicConformer) into the Hugging Face cache
#
# Set HF_TOKEN (in .env or the environment) if a model asks you to accept its terms.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
mkdir -p "$TOOLS/bin" "$TESSDATA_PREFIX" "$LOGS"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
have_sudo() { command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; }

step "Checking GPU"
if (( GPU_COUNT == 0 )); then
  echo "nvidia-smi not found or no GPU visible. This setup needs an NVIDIA GPU." >&2
  exit 1
fi
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv
echo "Plan: model $LLM_MODEL on GPU(s) $LLM_GPUS (mem fraction $GPU_MEM), speech on GPU(s) $APP_GPUS"

step "Installing uv (Python/package manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version
uv python install 3.12

step "Installing Tesseract OCR"
if [[ -z "${TESSERACT_CMD:-}" ]]; then
  if have_sudo && command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y -qq tesseract-ocr
    export TESSERACT_CMD="$(command -v tesseract)"
  else
    echo "No root access: installing Tesseract from conda-forge into $TOOLS/tess"
    if [[ ! -x "$TOOLS/bin/micromamba" ]]; then
      curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C "$TOOLS" bin/micromamba
    fi
    "$TOOLS/bin/micromamba" create -y -q -p "$TOOLS/tess" -c conda-forge tesseract
    export TESSERACT_CMD="$TOOLS/tess/bin/tesseract"
  fi
fi
"$TESSERACT_CMD" --version | head -1

step "Downloading OCR language data (mar, hin, ori, eng, osd)"
for l in mar hin ori eng osd; do
  f="$TESSDATA_PREFIX/$l.traineddata"
  [[ -s "$f" ]] || curl -fsSL -o "$f" "https://github.com/tesseract-ocr/tessdata_best/raw/main/$l.traineddata"
done
"$TESSERACT_CMD" --list-langs

step "Creating the vLLM environment ($VENV_VLLM)"
[[ -x "$VENV_VLLM/bin/python" ]] || uv venv --python 3.12 "$VENV_VLLM"
uv pip install --python "$VENV_VLLM/bin/python" vllm
"$VENV_VLLM/bin/python" -c "import vllm; print('vllm', vllm.__version__)"

step "Creating the application environment ($VENV_APP)"
[[ -x "$VENV_APP/bin/python" ]] || uv venv --python 3.12 "$VENV_APP"
uv pip install --python "$VENV_APP/bin/python" -r requirements-gpu.txt
"$VENV_APP/bin/python" -c "import torch, parler_tts; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

step "Installing Chromium for video recording"
if have_sudo; then
  "$VENV_APP/bin/python" -m playwright install --with-deps chromium
else
  "$VENV_APP/bin/python" -m playwright install chromium
  echo "(no root: if Chromium fails to start, ask an admin to run: playwright install-deps chromium)"
fi

step "Downloading model weights (this can take a while)"
models_ok=1
bash scripts/gpu/download_models.sh || models_ok=0

step "Running the test suite"
"$VENV_APP/bin/python" -m pytest -q

if (( models_ok )); then
  step "Setup complete"
  echo "Next: bash scripts/gpu/run_all.sh"
else
  step "Setup INCOMPLETE: some models are blocked (see the instructions above)"
  echo "After access is granted: bash scripts/gpu/download_models.sh, then bash scripts/gpu/run_all.sh"
  exit 1
fi
