import io
import wave

import numpy as np
import pytest

from services.stt.service import AudioRejected, validate as validate_audio
from services.tts.engines import Audio, ConsentMissing, load_consent
from services.tts.normalise import prepare_for_speech, sentences
from services.tts.service import AudioQualityError, check_audio, synthesize


class FakeEngine:
    def __init__(self, seconds_per_char=0.08, broken_first=False):
        self.spc, self.broken_first, self.calls = seconds_per_char, broken_first, 0

    def synthesize(self, chunks, lang, speaker=None):
        self.calls += 1
        sr = 16000
        n = int(sum(len(c) for c in chunks) * self.spc * sr)
        if self.broken_first and self.calls == 1:
            n = sr // 10  # stopped mid-sentence
        t = np.arange(n) / sr
        return Audio((0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr, "fake-tts", "Sunita")


def test_speech_text_preparation():
    text = "अकुशल श्रमिकांना ₹ 484/- प्रतिदिन [mp:p1:2], VDA 6% वाढ."
    assert prepare_for_speech(text, "mr") == "अकुशल श्रमिकांना रुपये 484 प्रतिदिन , वी डी ए 6 टक्के वाढ."


def test_sentence_chunking():
    text = "पहिले वाक्य. " + "हा एक लांब भाग आहे, " * 30
    chunks = sentences(text, max_chars=120)
    assert chunks[0] == "पहिले वाक्य." and all(len(c) <= 120 for c in chunks)


def test_synthesis_is_marked_synthetic_and_valid_wav():
    r = synthesize("रुग्णालयांनी दर मराठी आणि इंग्रजीत लावावेत.", "mr", FakeEngine())
    assert r.synthetic and r.model == "fake-tts"
    with wave.open(io.BytesIO(r.wav)) as w:
        assert w.getframerate() == 16000 and w.getnframes() > 0


def test_truncated_audio_is_regenerated():
    engine = FakeEngine(broken_first=True)
    r = synthesize("रुग्णालयांनी दर मराठी आणि इंग्रजीत लावावेत.", "mr", engine)
    assert engine.calls == 2 and r.duration_s > 1


def test_persistently_bad_audio_is_never_returned():
    with pytest.raises(AudioQualityError):
        synthesize("रुग्णालयांनी दर मराठी आणि इंग्रजीत लावावेत.", "mr", FakeEngine(seconds_per_char=0.001))


@pytest.mark.parametrize("samples,msg", [
    (np.zeros(16000, dtype=np.float32), "silent"),
    (np.ones(16000, dtype=np.float32), "clipped"),
    (np.array([np.nan] * 100, dtype=np.float32), "invalid"),
])
def test_audio_checks(samples, msg):
    with pytest.raises(AudioQualityError, match=msg):
        check_audio(Audio(samples, 16000, "m", "v"), "x")


def test_voice_cloning_requires_consent(tmp_path):
    with pytest.raises(ConsentMissing):
        load_consent("someone", tmp_path)
    (tmp_path / "someone").mkdir()
    (tmp_path / "someone" / "consent.yaml").write_text("speaker_name: A\nsigned_on: 2026-10-20\n", encoding="utf-8")
    with pytest.raises(ConsentMissing, match="permitted_use"):
        load_consent("someone", tmp_path)


@pytest.mark.parametrize("seconds,amp,msg", [(0.2, 0.3, "too short"), (61, 0.3, "longer"), (2, 0.0, "no speech")])
def test_stt_rejects_bad_recordings(seconds, amp, msg):
    samples = (amp * np.ones(int(seconds * 16000))).astype(np.float32)
    with pytest.raises(AudioRejected, match=msg):
        validate_audio(samples)
