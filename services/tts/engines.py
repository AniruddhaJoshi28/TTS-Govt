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

import numpy as np
import yaml

VOICES_DIR = Path(__file__).parents[2] / "data" / "voices"

# Named speakers recommended for each language on the Indic Parler-TTS model card.
PARLER_SPEAKERS = {"mr": ("Sanjay", "Sunita"), "hi": ("Rohit", "Divya"), "or": ("Manas", "Debjani"), "en": ("Thoma", "Mary")}

PARLER_STYLE = (
    "{speaker} speaks at a moderate, unhurried pace in a calm, warm and friendly tone, "
    "like a helpful local officer explaining something clearly. The recording is very high quality, "
    "with the voice sounding clear and close up, and no background noise."
)


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

    def synthesize(self, chunks: list[str], lang: str, speaker: str | None = None, pause_s: float = 0.35) -> Audio:
        speaker = speaker or PARLER_SPEAKERS[lang][0]
        desc = self.description_tokenizer(PARLER_STYLE.format(speaker=speaker), return_tensors="pt").to(self.device)
        pieces = []
        for text in chunks:
            prompt = self.tokenizer(text, return_tensors="pt").to(self.device)
            with self.torch.no_grad():
                out = self.model.generate(
                    input_ids=desc.input_ids, attention_mask=desc.attention_mask,
                    prompt_input_ids=prompt.input_ids, prompt_attention_mask=prompt.attention_mask,
                )
            pieces.append(out.cpu().numpy().squeeze().astype(np.float32))
            pieces.append(np.zeros(int(pause_s * self.sample_rate), dtype=np.float32))
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

    def synthesize(self, chunks: list[str], lang: str, speaker: str | None = None, pause_s: float = 0.35) -> Audio:
        pieces = []
        for text in chunks:
            audio = np.asarray(self.model(text, ref_audio_path=self.ref_audio, ref_text=self.consent["reference_text"]))
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            pieces.append(audio.astype(np.float32))
            pieces.append(np.zeros(int(pause_s * self.sample_rate), dtype=np.float32))
        return Audio(np.concatenate(pieces[:-1]), self.sample_rate, self.model_id, f"clone:{self.voice_id}")
