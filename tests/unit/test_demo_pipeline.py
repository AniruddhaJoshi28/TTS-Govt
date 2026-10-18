import importlib.util
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("make_demo_video", ROOT / "scripts" / "demo" / "make_demo_video.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_srt_format():
    srt = demo.make_srt([(0.0, 2.5, "नमस्कार."), (61.234, 3725.0, "ଧନ୍ୟବାଦ।")])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,500\nनमस्कार.\n")
    assert "2\n00:01:01,234 --> 01:02:05,000\nଧନ୍ୟବାଦ।" in srt


def test_mix_places_clips_and_avoids_clipping():
    sr = 16000
    tone = np.full(sr, 0.8, dtype=np.float32)  # 1 s
    track = demo.mix(3.0, [(0.0, tone, sr), (0.5, tone, sr)])
    assert track.size == 3 * demo.SR + 1
    assert np.max(np.abs(track)) <= 0.95 + 1e-6
    assert track[int(2.5 * demo.SR)] == 0.0


def test_wav_roundtrip():
    x = (0.5 * np.sin(np.linspace(0, 20, 4410))).astype(np.float32)
    y, sr = demo.decode_wav(demo.encode_wav(x))
    assert sr == demo.SR and np.allclose(x, y, atol=1e-3)


def test_stub_models_are_refused():
    assert demo.STUB_MODEL.search("UI-TEST-STUB")
    assert not demo.STUB_MODEL.search("Qwen/Qwen3-8B")


def test_scene_file_is_complete():
    videos = yaml.safe_load((ROOT / "docs" / "demo_scripts" / "scenes.yaml").read_text(encoding="utf-8"))["videos"]
    assert set(videos) == {"MH", "MP", "OD"}
    for state, v in videos.items():
        actions = [s["action"] for s in v["scenes"]]
        assert actions[0] == "title_card" and actions[-1] == "closing_card"
        assert {"overview", "document", "summary", "open_citation", "ask", "listen_answer"} <= set(actions)
        assert {"title", "subtitle", "closing"} <= set(v["card"])
        assert v["narrator"] != v["product_voice"], "narrator and product voice must be distinguishable"
        assert "AI" in v["label"] and "AI" in v["scenes"][-1]["narration"], "synthetic narration must be disclosed"
        for s in v["scenes"]:
            if s["action"] == "ask":
                assert s["expect"] in ("answered", "insufficient_evidence")


def test_concat_list_holds_each_frame_until_the_next():
    frames = [(100.0, "f0.jpg"), (100.5, "f1.jpg"), (102.0, "f2.jpg")]
    script = demo.concat_list(frames, 103.0)
    assert script.startswith("ffconcat version 1.0")
    assert "file 'f0.jpg'\nduration 0.5000" in script
    assert "file 'f1.jpg'\nduration 1.5000" in script
    assert "file 'f2.jpg'\nduration 1.0000" in script
    assert script.rstrip().endswith("file 'f2.jpg'")


def test_polish_trims_silence_and_levels():
    from services.tts.postprocess import plausible, polish

    sr = 16000
    voice = (0.05 * np.sin(np.arange(sr) / 5)).astype(np.float32)
    x = np.concatenate([np.zeros(sr), voice, np.zeros(sr)])
    y = polish(x, sr)
    assert 0.9 * sr < y.size < 1.3 * sr  # leading/trailing second of silence removed
    assert abs(20 * np.log10(np.sqrt(np.mean(y ** 2))) + 20) < 1.5  # levelled to about -20 dBFS
    assert plausible(3.0, "अकुशल श्रमिकांना दैनिक दर") and not plausible(0.3, "अकुशल श्रमिकांना दैनिक दर लागू")
