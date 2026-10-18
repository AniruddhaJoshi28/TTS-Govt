"""Makes generated speech sound less machine-like (plan §3E, path 2).

Each sentence is generated separately, then:
- leading/trailing silence and breath noise are trimmed, so pauses are the ones
  we choose, not random gaps from the model;
- a short fade in/out removes clicks at the joins;
- loudness is levelled so sentences do not jump in volume;
- sentences whose length is implausible for their text (cut off, or rambling)
  are flagged so the engine can regenerate them.
"""

import numpy as np

# Natural speaking rate is roughly 10–15 characters per second in these scripts.
MIN_CHARS_PER_SECOND = 5.0
MAX_CHARS_PER_SECOND = 22.0


def trim_silence(x: np.ndarray, sr: int, threshold_db: float = -40.0, pad_s: float = 0.04) -> np.ndarray:
    if x.size == 0:
        return x
    frame = max(1, int(0.02 * sr))
    n = x.size // frame
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    loud = np.where(20 * np.log10(rms / (np.max(rms) + 1e-12)) > threshold_db)[0]
    if loud.size == 0:
        return x[:0]
    pad = int(pad_s * sr)
    start = max(0, loud[0] * frame - pad)
    end = min(x.size, (loud[-1] + 1) * frame + pad)
    return x[start:end]


def fade(x: np.ndarray, sr: int, ms: float = 15.0) -> np.ndarray:
    n = min(int(sr * ms / 1000), x.size // 2)
    if n == 0:
        return x
    y = x.astype(np.float32).copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def level(x: np.ndarray, target_dbfs: float = -20.0, peak: float = 0.95) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0
    if rms == 0.0:
        return x
    y = x * (10 ** (target_dbfs / 20) / rms)
    top = float(np.max(np.abs(y)))
    return (y * (peak / top) if top > peak else y).astype(np.float32)


def plausible(seconds: float, text: str) -> bool:
    chars = len(text.replace(" ", ""))
    return chars / MAX_CHARS_PER_SECOND <= seconds <= chars / MIN_CHARS_PER_SECOND + 1.5


def polish(x: np.ndarray, sr: int) -> np.ndarray:
    return level(fade(trim_silence(x.astype(np.float32), sr), sr))


def pause(seconds: float, sr: int) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.float32)
