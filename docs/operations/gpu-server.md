# Running the full pipeline on the GPU server

This runbook takes a Linux GPU server from a fresh checkout to three recorded demo videos. On the laptop, everything except the model, TTS and STT runs and is tested. Those three need a GPU.

## 1. What runs where

| Component | Model | Environment | GPU memory (approx.) |
| --- | --- | --- | --- |
| Summaries and Q&A | `Qwen/Qwen3-8B` via vLLM | `vllm` env | 18–20 GB at bf16 |
| Regional speech (TTS) | `ai4bharat/indic-parler-tts` | `app` env | ~4 GB |
| Spoken questions (STT) | `ai4bharat/indic-conformer-600m-multilingual` | `app` env | ~3 GB |
| OCR | Tesseract 5 + `mar`, `hin`, `ori` (tessdata_best) | system | none |

A single 40 GB or larger GPU (A100/A6000/L40S) fits everything. On a 24 GB card, run TTS/STT on a second GPU (`CUDA_VISIBLE_DEVICES`) or reduce `GPU_MEM`.

vLLM and parler-tts need different `transformers` versions, so they live in **separate** environments.

## 2. One-time setup

```bash
git clone <repo> && cd TTS-Govt
sudo apt-get install -y tesseract-ocr
for l in mar hin ori; do
  sudo wget -q -O /usr/share/tesseract-ocr/5/tessdata/$l.traineddata \
    https://github.com/tesseract-ocr/tessdata_best/raw/main/$l.traineddata
done
tesseract --list-langs   # must list mar, hin, ori

# vLLM environment
python3 -m venv ~/venvs/vllm && ~/venvs/vllm/bin/pip install vllm

# App environment
python3 -m venv ~/venvs/app && source ~/venvs/app/bin/activate
pip install -r requirements-gpu.txt
python -m playwright install --with-deps chromium
```

Some AI4Bharat models ask you to accept their terms on Hugging Face first. Accept them on the model pages, then run `huggingface-cli login` (or set `HF_TOKEN`). If IndicConformer fails to load, install any extra packages listed on its model card.

## 3. Start the services

```bash
# Terminal 1: model server
source ~/venvs/vllm/bin/activate
bash scripts/gpu/serve_llm.sh                 # LLM_MODEL=... to try another model

# Terminal 2: app (builds the corpus from the official sources, then serves on :8000)
source ~/venvs/app/bin/activate
bash scripts/gpu/run_app.sh
```

Check `curl localhost:8000/api/v1/health`. Every dependency should be `ok`. To use the UI from your laptop, tunnel the port: `ssh -L 8000:127.0.0.1:8000 <server>`, then open http://localhost:8000.

## 4. Pick the model on evidence

Serve each candidate on its own port, then run:

```bash
python evaluation/summarisation/compare_models.py \
  --model Qwen/Qwen3-8B=http://127.0.0.1:8001/v1 \
  --model sarvamai/sarvam-m=http://127.0.0.1:8002/v1
```

Suggested candidates are `Qwen/Qwen3-8B` (default), `Qwen/Qwen3-14B`, `sarvamai/sarvam-m` (Indic-tuned, larger) and `google/gemma-3-12b-it`. Prefer the model with the lowest rejection rate and good section coverage **in each language separately**. Then have native speakers read the outputs; the numbers only screen candidates.

## 5. Before recording: human checks

1. **Sign the MP review file.** `data/review/mp-2026-09-30-minimum-wages-vda.yaml` holds an AI-proposed transcription of the wage table. A team member compares it with page 1 of the official PDF, fixes anything wrong, and fills in `reviewer` and `reviewed_at`. Then rebuild with `python scripts/build_corpus.py`. Until then, the MP summary withholds the wage figures, which is correct behaviour.
2. **Read the scripts.** A native speaker of each language reviews `docs/demo_scripts/scenes.yaml` and the UI strings in `apps/web/app.js`.
3. **Listen to the voices.** Generate one sentence per language from the UI ("Listen") and confirm the pronunciation. Add fixes to `data/lexicons/<lang>.yaml`.
4. **Optional, real spoken questions.** Put a consented recording of a real person asking each scene question at `data/demo/questions/MH.wav`, `MP.wav` and `OD.wav` (16-bit WAV). Without these files the question is typed on screen.

## 6. Record the videos

```bash
bash scripts/gpu/make_all_videos.sh
```

For each state, `output/demo/<STATE>/` will contain:

- `demo_<STATE>.mp4`: 1080p, narration and product audio, soft subtitles
- `captions.srt`: subtitles in the regional script
- `narration.wav`: the full soundtrack
- `evidence.json`: the document and checksum, model, every answer shown, voices used, and a reviewer checklist

The script **aborts** instead of recording if:

- the model looks like a stub;
- TTS is down;
- an answer contradicts the narration (for example, the "unknown" question gets answered instead of declined);
- narration audio fails its quality checks.

If it aborts, read the reason, fix the cause, then rerun.

## 7. Voice cloning, if you want a specific person's voice

Indic Parler-TTS ships natural regional voices. To speak in a particular person's voice (for example, the client's chosen narrator), use IndicF5:

1. Record 5–15 seconds of that person in a quiet room and get their written consent. See `data/voices/README.md`.
2. Start the app with `TTS_ENGINE=clone:<voice_id>`.

The output is still synthetic speech and keeps its AI-voice label. Neither the UI nor the videos present it as a human recording.

## 8. Before sending to the client

Use `evidence.json` as the checklist. Have a reviewer:

- compare every number and date on screen with the official PDF;
- watch the whole video with a native speaker;
- sign off.

The plan (§8) prefers human narration for client videos. These AI-narrated videos are labelled throughout, so that choice can be revisited without re-recording the product footage.
