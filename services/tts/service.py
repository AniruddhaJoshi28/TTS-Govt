"""Speech synthesis with integrity checks and synthetic-voice disclosure (plan §3E).

Generated audio is rejected, never played, if it is empty, clipped, contains
NaNs, or is implausibly short for the text (a sign it stopped mid-sentence).
Every result is marked synthetic so no interface can present it as a human
recording.
"""

import io
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import numpy as np

from services.tts.engines import Audio
from services.tts.normalise import prepare_for_speech, sentences

# Conservative lower bound on speaking time; real speech is slower than this.
MAX_CHARS_PER_SECOND = 28.0
MIN_RMS = 0.005


class Engine(Protocol):
    def synthesize(self, chunks: list[str], lang: str, speaker: str | None = None) -> Audio: ...


class AudioQualityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechResult:
    wav: bytes
    duration_s: float
    model: str
    voice: str
    spoken_text: str
    synthetic: bool = True
    created_at: str = ""


def check_audio(audio: Audio, spoken_text: str) -> float:
    x = audio.samples
    if x.size == 0 or not np.all(np.isfinite(x)):
        raise AudioQualityError("empty or invalid audio")
    duration = x.size / audio.sample_rate
    if float(np.sqrt(np.mean(x**2))) < MIN_RMS:
        raise AudioQualityError("audio is silent")
    if float(np.mean(np.abs(x) >= 0.999)) > 0.01:
        raise AudioQualityError("audio is clipped")
    min_duration = len(spoken_text.replace(" ", "")) / MAX_CHARS_PER_SECOND
    if duration < min_duration:
        raise AudioQualityError(f"audio too short ({duration:.1f}s for {len(spoken_text)} chars): likely truncated")
    return duration


def to_wav(audio: Audio) -> bytes:
    pcm = (np.clip(audio.samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def synthesize(text: str, lang: str, engine: Engine, speaker: str | None = None, attempts: int = 2) -> SpeechResult:
    spoken = prepare_for_speech(text, lang)
    if not spoken:
        raise AudioQualityError("nothing to speak")
    last: Exception | None = None
    for _ in range(attempts):
        audio = engine.synthesize(sentences(spoken), lang, speaker)
        try:
            duration = check_audio(audio, spoken)
        except AudioQualityError as exc:
            last = exc
            continue
        return SpeechResult(to_wav(audio), duration, audio.model, audio.voice, spoken,
                            created_at=datetime.now(timezone.utc).isoformat())
    raise AudioQualityError(f"audio failed quality checks: {last}")
