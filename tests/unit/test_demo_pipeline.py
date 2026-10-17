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
        assert actions[0] == "home" and "listen_answer" in actions and "open_citation" in actions
        assert v["narrator"] != v["product_voice"], "narrator and product voice must be distinguishable"
        assert "AI" in v["label"] and "AI" in v["scenes"][-1]["narration"], "synthetic narration must be disclosed"
        for s in v["scenes"]:
            if s["action"] == "ask":
                assert s["expect"] in ("answered", "insufficient_evidence")
