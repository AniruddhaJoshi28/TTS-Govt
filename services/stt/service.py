"""Speech-to-text for spoken questions (Workstream D).

Audio is validated (decodable, 0.5–60 s, not silent) before recognition. The
transcript is always returned for the user to confirm or correct before it is
used as a question, because the model gives no reliable confidence score and
a misheard number or name must never be acted on silently.
"""

import subprocess
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
MIN_SECONDS, MAX_SECONDS = 0.5, 60.0
MIN_RMS = 0.003
SUPPORTED = {"mr", "hi", "or"}


class AudioRejected(ValueError):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    duration_s: float
    model: str
    needs_confirmation: bool = True


def decode_to_pcm(data: bytes) -> np.ndarray:
    """Any browser recording (webm/ogg/wav) → 16 kHz mono float32, via ffmpeg."""
    import imageio_ffmpeg

    proc = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        input=data, capture_output=True, timeout=60, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise AudioRejected("the recording could not be decoded")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def validate(samples: np.ndarray) -> float:
    duration = samples.size / SAMPLE_RATE
    if duration < MIN_SECONDS:
        raise AudioRejected("the recording is too short")
    if duration > MAX_SECONDS:
        raise AudioRejected("the recording is longer than 60 seconds")
    if float(np.sqrt(np.mean(samples**2))) < MIN_RMS:
        raise AudioRejected("no speech was detected; please speak closer to the microphone")
    return duration


class IndicConformerSTT:
    model_id = "ai4bharat/indic-conformer-600m-multilingual"

    def __init__(self, device: str | None = None):
        import torch
        from transformers import AutoModel

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = AutoModel.from_pretrained(self.model_id, trust_remote_code=True)

    def transcribe(self, samples: np.ndarray, language: str) -> str:
        wav = self.torch.from_numpy(samples.copy()).unsqueeze(0)
        return str(self.model(wav, language, "rnnt")).strip()


def transcribe(data: bytes, language: str, engine) -> Transcript:
    if language not in SUPPORTED:
        raise AudioRejected(f"spoken questions are supported in Marathi, Hindi and Odia, not {language!r}")
    samples = decode_to_pcm(data)
    duration = validate(samples)
    text = engine.transcribe(samples, language)
    if not text:
        raise AudioRejected("no words were recognised; please try again")
    return Transcript(text, language, duration, getattr(engine, "model_id", "unknown"))
