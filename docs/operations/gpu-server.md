# Running everything on the GPU server

Four commands take a Linux GPU server from nothing to three recorded demo videos. Root access is not required.

```bash
git clone https://github.com/AniruddhaJoshi28/TTS-Govt.git
cd TTS-Govt && git checkout feature/foundation-and-ingestion
bash scripts/gpu/setup.sh      # once: Python, OCR, both environments, model weights, tests
bash scripts/gpu/run_all.sh    # start model + app, build corpus, record the 3 videos
```

The videos land in `output/demo/MH/`, `output/demo/MP/` and `output/demo/OD/`. Run `bash scripts/gpu/stop_all.sh` to stop the services.

Before you record videos for the client, do the [human checks](#before-recording-for-the-client).

## What setup.sh installs

| Item | Where | Notes |
| --- | --- | --- |
| `uv` + Python 3.12 | `~/.local/bin` | Works even if the server's Python is older |
| Tesseract OCR | system (`apt`, if you have sudo), else conda-forge into `.tools/tess` | |
| OCR language data | `.tools/tessdata` | `mar`, `hin`, `ori`, `eng` from tessdata_best |
| vLLM | `.venvs/vllm` | Serves the summarisation model |
| App + Indic Parler-TTS + Playwright | `.venvs/app` | Separate from vLLM because their `transformers` versions conflict |
| Model weights | Hugging Face cache (`~/.cache/huggingface`) | Qwen3, `ai4bharat/indic-parler-tts`, `ai4bharat/indic-conformer-600m-multilingual` |

You need about 40 GB of free disk space. Setup ends by running the test suite.

### Hugging Face access

Some AI4Bharat models ask you to accept their terms first. If setup prints `FAILED: ai4bharat/...`:
1. Log in at huggingface.co and open the model page it names. Accept the terms.
2. Create an access token (Settings → Access Tokens, type "Read").
3. Put it in `.env` at the repository root (`HF_TOKEN=hf_...`), then re-run `bash scripts/gpu/setup.sh`. Finished steps are skipped.

## How the GPU is used

`scripts/gpu/env.sh` detects the GPUs and chooses automatically:

| GPUs found | Model | Placement |
| --- | --- | --- |
| 2 or more | Qwen3-8B | Model on GPU 0, speech on GPU 1 |
| 1 GPU, 40 GB or more | Qwen3-8B | Shared (model uses 55% of memory) |
| 1 GPU, under 40 GB | Qwen3-4B | Shared |

You can override any setting in `.env`, for example `LLM_MODEL=Qwen/Qwen3-14B`, `LLM_GPUS=2`, `APP_GPUS=3` or `GPU_MEM=0.5`. If you change `LLM_MODEL`, re-run `setup.sh` to download it.

## Using the app interactively

```bash
bash scripts/gpu/run_all.sh --serve     # start services without recording
```

On your laptop, run `ssh -L 8000:127.0.0.1:8000 <user>@<server>`, then open http://localhost:8000. Try a summary, a question and "Listen" in each state. Record afterwards with `bash scripts/gpu/make_all_videos.sh`.

## Before recording for the client

1. **Sign the MP wage table.** Open `data/review/mp-2026-09-30-minimum-wages-vda.yaml` and compare it with page 1 of the official PDF (`data/raw/mp-2026-09-30-minimum-wages-vda.pdf`). Correct anything wrong, fill in `reviewer:` and `reviewed_at:`, then run `.venvs/app/bin/python scripts/build_corpus.py`. Until this is signed, the MP summary withholds the wage figures. That's intended behaviour, because OCR misreads the digit 1 in that scan.
2. **Native-speaker review** of the narration in `docs/demo_scripts/scenes.yaml` and the interface text in `apps/web/app.js`.
3. **Listen** to one answer per language in the UI. Fix any mispronounced terms in `data/lexicons/<mr|hi|or>.yaml`.
4. **Optional, real spoken questions.** Put a consented 16-bit WAV of a real person asking each scene question at `data/demo/questions/MH.wav`, `MP.wav` and `OD.wav`. Without these files the question is typed on screen.

## What the video recorder checks

For each state it:
1. checks the model, TTS and corpus;
2. generates the summary and answers, and confirms each answer matches its narration;
3. generates the narration;
4. records the real UI at 1080p;
5. mixes in the narration and the product's own voice;
6. writes the outputs below.

| Output | Contents |
| --- | --- |
| `demo_<STATE>.mp4` | Video, audio, regional subtitles |
| `captions.srt` | Subtitles |
| `narration.wav` | Soundtrack |
| `evidence.json` | Document checksum, model, every answer shown, voices, reviewer checklist |

It stops with `ABORTED: <reason>` rather than producing a misleading video when:

- the model is a test stub;
- TTS is down or audio fails its quality checks;
- an answer contradicts the narration. For example, the "unknown" question gets an answer instead of being declined, or a real question is declined.

Answers can vary slightly between runs. If one aborts, re-run that state, for example `.venvs/app/bin/python scripts/demo/make_demo_video.py --state MP`. If it keeps happening, adjust that scene's question in `scenes.yaml`.

## Choosing the best model

Serve two candidates on different ports, then compare them on the real documents:

```bash
source scripts/gpu/env.sh
CUDA_VISIBLE_DEVICES=0 .venvs/vllm/bin/vllm serve Qwen/Qwen3-8B --port 8001 &
CUDA_VISIBLE_DEVICES=1 .venvs/vllm/bin/vllm serve sarvamai/sarvam-m --port 8002 &
.venvs/app/bin/python evaluation/summarisation/compare_models.py \
  --model Qwen/Qwen3-8B=http://127.0.0.1:8001/v1 --model sarvamai/sarvam-m=http://127.0.0.1:8002/v1
```

The output is in `output/evaluation/model_comparison.csv`. Prefer low rejection rates with good section coverage **for each language separately**, then have native speakers read the outputs.

## Speaking in a specific person's voice

To use a real narrator's voice instead of the built-in voices, follow `data/voices/README.md`. You need a 5–15 second recording and that person's written consent. Then set `TTS_ENGINE=clone:<voice_id>` in `.env` and add `ai4bharat/IndicF5` to the downloads in `setup.sh`. The output is still labelled AI-generated.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `vllm exited` with CUDA or driver errors | `nvidia-smi` must show a driver that supports CUDA 12. Ask the admin, or pin an older vLLM: `uv pip install --python .venvs/vllm/bin/python "vllm<0.X"` |
| vLLM out of memory | Set `GPU_MEM=0.45` or `MAX_MODEL_LEN=16384` in `.env`, or `LLM_MODEL=Qwen/Qwen3-4B` |
| `tts unavailable` in the health check | Read `logs/app.log`. Usually the model terms haven't been accepted (see Hugging Face access) or memory is short |
| `stt unavailable` | Voice input only; the videos still work. Install any extra packages listed on the IndicConformer model card into `.venvs/app` |
| Chromium fails to launch | Ask an admin to run `.venvs/app/bin/python -m playwright install-deps chromium` |
| `ABORTED: ... contradicts narration` | Re-run that state; if it repeats, look at the answer in the UI and adjust the question in `scenes.yaml` |
| Port already in use | Set `PORT=8100` and `LLM_PORT=8101` in `.env` |
| A portal changed and download fails | The script reports which document; `data/raw/` can also be filled manually with the official PDFs |

Send me `logs/app.log`, `logs/vllm.log` or the error text and I'll fix the cause.
