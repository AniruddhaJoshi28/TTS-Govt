"""TTS engines (Workstream E, path 2). Heavy imports happen lazily, on the GPU host.

- IndicParlerTTS: AI4Bharat's Indic Parler-TTS. Natural, expressive voices for
  Marathi, Hindi and Odia, steered by a plain-language voice description.
- IndicF5Clone: AI4Bharat's IndicF5, which speaks in the voice of a reference
  recording. It refuses to run unless that speaker's signed consent record is
  present (data/voices/<voice_id>/consent.yaml).

All output is synthetic speech and is labelled as such by the service layer.
"""

from dataclasses import dataclass
from pathlib import Path
import os

import numpy as np
import yaml

from services.tts.postprocess import pause, plausible, polish

VOICES_DIR = Path(__file__).parents[2] / "data" / "voices"

# Named speakers recommended for each language on the Indic Parler-TTS model card.
PARLER_SPEAKERS = {"mr": ("Sanjay", "Sunita"), "hi": ("Rohit", "Divya"), "or": ("Manas", "Debjani"), "en": ("Thoma", "Mary")}
DEFAULT_SPEAKERS = {
    "mr": os.environ.get("TTS_VOICE_MR", "Sunita"),
    "hi": os.environ.get("TTS_VOICE_HI", "Divya"),
    "or": os.environ.get("TTS_VOICE_OR", "Debjani"),
    "en": os.environ.get("TTS_VOICE_EN", "Mary"),
}

# Indic Parler-TTS is steered by a plain-language description. Words like "expressive",
# "moderate pace" and "very clear, close-up recording" move it away from a flat, read-out
# delivery towards a person explaining something.
PARLER_STYLE = (
    "{speaker} is a fluent native speaker. {speaker} speaks clearly at a moderate pace, "
    "with accurate pronunciation, natural intonation, and brief pauses at commas and full stops, "
    "like a person calmly explaining important government information to a citizen. "
    "The recording is of very high quality, with the voice sounding very clear and close up, "
    "and there is no background noise."
)

SENTENCE_PAUSE_S = 0.42
MAX_TAKES = max(1, int(os.environ.get("TTS_MAX_TAKES", "1")))


class ConsentMissing(PermissionError):
    pass


@dataclass(frozen=True)
class Audio:
    samples: np.ndarray  # float32 mono in [-1, 1]
    sample_rate: int
    model: str
    voice: str


class IndicParlerTTS:
    model_id = "ai4bharat/indic-parler-tts"

    def __init__(self, device: str | None = None):
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        self.torch = torch
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model = ParlerTTSForConditionalGeneration.from_pretrained(self.model_id).to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self.description_tokenizer = AutoTokenizer.from_pretrained(self.model.config.text_encoder._name_or_path)
        self.sample_rate = self.model.config.sampling_rate
        self._descriptions = {}

    def _take(self, desc, text: str) -> np.ndarray:
        prompt = self.tokenizer(text, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            out = self.model.generate(
                input_ids=desc.input_ids, attention_mask=desc.attention_mask,
                prompt_input_ids=prompt.input_ids, prompt_attention_mask=prompt.attention_mask,
                do_sample=True, temperature=0.8,
            )
        return polish(out.cpu().numpy().squeeze().astype(np.float32), self.sample_rate)

    def synthesize(self, chunks: list[str], lang: str, speaker: str | None = None,
                   pause_s: float = SENTENCE_PAUSE_S) -> Audio:
        speaker = speaker or DEFAULT_SPEAKERS[lang]
        if speaker not in PARLER_SPEAKERS[lang]:
            raise ValueError(f"unsupported {lang!r} speaker {speaker!r}")
        if speaker not in self._descriptions:
            self._descriptions[speaker] = self.description_tokenizer(
                PARLER_STYLE.format(speaker=speaker), return_tensors="pt"
            ).to(self.device)
        desc = self._descriptions[speaker]
        pieces = []
        for text in chunks:
            best = None
            for _ in range(MAX_TAKES):
                take = self._take(desc, text)
                if plausible(take.size / self.sample_rate, text):
                    best = take
                    break
                # keep the take whose length is closest to a natural speaking rate
                target = len(text.replace(" ", "")) / 12.0
                if best is None or abs(take.size / self.sample_rate - target) < abs(best.size / self.sample_rate - target):
                    best = take
            pieces += [best, pause(pause_s, self.sample_rate)]
        return Audio(np.concatenate(pieces[:-1]), self.sample_rate, self.model_id, speaker)


def load_consent(voice_id: str, voices_dir: Path = VOICES_DIR) -> dict:
    path = voices_dir / voice_id / "consent.yaml"
    if not path.exists():
        raise ConsentMissing(f"no consent record for voice {voice_id!r} at {path}")
    record = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("speaker_name", "signed_on", "permitted_use", "reference_audio", "reference_text"):
        if not record.get(key):
            raise ConsentMissing(f"consent record for {voice_id!r} is missing {key!r}")
    return record


class IndicF5Clone:
    model_id = "ai4bharat/IndicF5"
    sample_rate = 24000

    def __init__(self, voice_id: str, voices_dir: Path = VOICES_DIR):
        self.consent = load_consent(voice_id, voices_dir)  # before any model download
        self.voice_id = voice_id
        self.ref_audio = str(voices_dir / voice_id / self.consent["reference_audio"])
        from transformers import AutoModel

        self.model = AutoModel.from_pretrained(self.model_id, trust_remote_code=True)

    def synthesize(self, chunks: list[str], lang: str, speaker: str | None = None,
                   pause_s: float = SENTENCE_PAUSE_S) -> Audio:
        pieces = []
        for text in chunks:
            audio = np.asarray(self.model(text, ref_audio_path=self.ref_audio, ref_text=self.consent["reference_text"]))
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            pieces += [polish(audio.astype(np.float32), self.sample_rate), pause(pause_s, self.sample_rate)]
        return Audio(np.concatenate(pieces[:-1]), self.sample_rate, self.model_id, f"clone:{self.voice_id}")
