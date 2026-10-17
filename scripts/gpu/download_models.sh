#!/usr/bin/env bash
# Download (or resume) all model weights. Exits non-zero if any model is blocked.
#   bash scripts/gpu/download_models.sh
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT"
if [[ -n "${HF_TOKEN:-}" ]]; then echo "Using HF_TOKEN from the environment/.env"; else echo "HF_TOKEN not set"; fi

"$VENV_VLLM/bin/python" - "$LLM_MODEL" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[1])
print("ok:", sys.argv[1])
PY

"$VENV_APP/bin/python" - <<'PY'
import sys
from huggingface_hub import snapshot_download
from huggingface_hub.utils import GatedRepoError

failed = []
for repo in ["ai4bharat/indic-parler-tts", "ai4bharat/indic-conformer-600m-multilingual"]:
    try:
        snapshot_download(repo)
        print("ok:", repo)
    except GatedRepoError:
        failed.append(repo)
        print(f"BLOCKED: {repo} needs access approval for your Hugging Face account")
    except Exception as exc:
        failed.append(repo)
        print(f"FAILED: {repo}: {type(exc).__name__}: {exc}")
if failed:
    print("\nTo fix:")
    print("  1. Log in at https://huggingface.co with the account that owns your token.")
    for repo in failed:
        print(f"  2. Open https://huggingface.co/{repo} and request/accept access.")
    print("  3. Create a Read token at https://huggingface.co/settings/tokens and add HF_TOKEN=hf_... to .env")
    print("  4. Re-run: bash scripts/gpu/download_models.sh")
    sys.exit(1)
PY
