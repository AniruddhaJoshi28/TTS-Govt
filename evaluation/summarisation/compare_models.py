"""Compares candidate SLMs on the real corpus, so model choice rests on evidence.

    python evaluation/summarisation/compare_models.py \
        --model Qwen/Qwen3-8B=http://127.0.0.1:8001/v1 \
        --model sarvamai/sarvam-m=http://127.0.0.1:8002/v1

For every document and its own language it records: whether a valid summary
was produced, sections stated, claims kept and claims rejected by factual
validation (unsupported numbers, invented citations), and latency. A lower
rejection rate with good coverage is better. This is a screening metric: the
native-speaker and domain review in plan §11 still decides.
"""

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.document_ingestion.corpus import load_corpus  # noqa: E402
from services.slm_orchestrator.llm import LLMConfig, LLMUnavailable, OpenAICompatibleLLM  # noqa: E402
from services.slm_orchestrator.summarise import summarise  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True, help="name=base_url (repeatable)")
    ap.add_argument("--corpus", type=Path, default=ROOT / "data" / "corpus")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "evaluation" / "model_comparison.csv")
    args = ap.parse_args()

    docs = load_corpus(args.corpus)
    rows = []
    for spec in args.model:
        name, base = spec.split("=", 1)
        llm = OpenAICompatibleLLM(LLMConfig(base_url=base.rstrip("/"), model=name))
        for doc in docs.values():
            t = time.monotonic()
            try:
                r = summarise(doc.to_passages(), doc.entry.language, llm)
                status = r.status
            except LLMUnavailable as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                break
            kept = sum(len(s.claims) for s in r.sections)
            rows.append({
                "model": name, "document": doc.entry.id, "language": doc.entry.language.value, "status": status,
                "sections_stated": sum(s.status == "stated" for s in r.sections),
                "claims_kept": kept, "claims_rejected": len(r.rejected),
                "rejection_rate": round(len(r.rejected) / (kept + len(r.rejected)), 3) if kept + len(r.rejected) else "",
                "seconds": round(time.monotonic() - t, 1),
            })
            print(rows[-1])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["model"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
