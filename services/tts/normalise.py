"""Prepares text for speech (Workstream E, path 2: normalisation and lexicons).

Removes citation markers, spells out symbols the TTS model reads badly, and
applies the reviewer-maintained pronunciation lexicon in data/lexicons/.

Not done yet: digits are left as digits. Number-to-words for Marathi, Hindi
and Odia must be written and checked by native speakers before it is used,
because a wrongly spoken amount is worse than an unnatural one.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml

LEXICON_DIR = Path(__file__).parents[2] / "data" / "lexicons"

SYMBOLS = {
    "mr": {"₹": "रुपये ", "%": " टक्के", "/-": ""},
    "hi": {"₹": "रुपये ", "%": " प्रतिशत", "/-": ""},
    "or": {"₹": "ଟଙ୍କା ", "%": " ପ୍ରତିଶତ", "/-": ""},
    "en": {"₹": "rupees ", "%": " percent", "/-": ""},
}


@lru_cache
def lexicon(lang: str) -> dict[str, str]:
    """Written form → spoken form, e.g. "VDA" → "वी डी ए". Longest entries apply first."""
    path = LEXICON_DIR / f"{lang}.yaml"
    if not path.exists():
        return {}
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(sorted(entries.items(), key=lambda kv: -len(kv[0])))


def prepare_for_speech(text: str, lang: str) -> str:
    text = re.sub(r"\[[^\]]*\]", "", text)  # citation markers
    for written, spoken in SYMBOLS.get(lang, {}).items():
        text = text.replace(written, spoken)
    for written, spoken in lexicon(lang).items():
        text = re.sub(rf"(?<!\w){re.escape(written)}(?!\w)", spoken, text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text: str, max_chars: int = 220) -> list[str]:
    """Split into chunks the TTS model can say in one breath."""
    parts = [p.strip() for p in re.split(r"(?<=[।॥.!?])\s+", text) if p.strip()]
    chunks: list[str] = []
    for p in parts:
        while len(p) > max_chars:
            cut = p.rfind(",", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 3 else p.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            chunks.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            chunks.append(p)
    return chunks
