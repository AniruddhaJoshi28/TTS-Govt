"""BM25 passage retrieval for Marathi, Hindi, Odia and English (Workstream C).

The multilingual vector index and reranker are added alongside this in weeks
6–8; BM25 stays as the internal fallback that needs no external service.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from services.metadata_extraction.normalise import normalise_digits

# \w alone splits Indic words at vowel signs (they are not alphanumeric), so the
# Devanagari and Odia blocks are included explicitly.
_TOKEN = re.compile(r"[\wऀ-ॿ଀-୿]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(normalise_digits(text).lower())


def index_terms(text: str) -> list[str]:
    """Words plus character trigrams of longer words.

    Marathi and Hindi inflect heavily ("भाषेत", "भाषांमध्ये") and compounds are
    written both joined and split ("दरपत्रक", "दर पत्रक"); whole-word matching
    misses these. Trigrams (prefixed "#", so they never collide with words)
    recover shared stems until the multilingual vector index is added.
    """
    terms = []
    for w in tokenize(text):
        terms.append(w)
        if len(w) >= 4:
            terms += [f"#{w[i:i + 3]}" for i in range(len(w) - 2)]
    return terms


@dataclass(frozen=True)
class Passage:
    passage_id: str
    document_id: str
    version_id: str
    url: str
    page: int
    text: str
    origin: str = "embedded"  # "embedded" | "ocr" | "reviewed"
    # Character spans of numbers that may be misread; never usable as evidence.
    untrusted: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float


class BM25Index:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75):
        self.passages = passages
        self.k1, self.b = k1, b
        self._tf = [Counter(index_terms(p.text)) for p in passages]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if passages else 0.0
        df = Counter(term for tf in self._tf for term in tf)
        n = len(passages)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> list[Hit]:
        """Top passages scoring above ``min_score``. Empty means no reliable evidence.

        BM25 scores scale with corpus size, so a stricter threshold must be
        calibrated on the real corpus (evaluation/retrieval), not fixed here.
        """
        terms = set(index_terms(query))
        hits = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            for t in terms:
                if t not in tf:
                    continue
                f = tf[t]
                norm = self.k1 * (1 - self.b + self.b * self._len[i] / self._avg)
                score += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if score > min_score:
                hits.append(Hit(self.passages[i], score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
