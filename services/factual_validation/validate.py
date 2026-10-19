"""Validates SLM output against the passages it cites (Workstream C, plan §4).

A claim survives only if it cites at least one passage that was actually
retrieved, and every number, date and rupee amount it states appears in the
trusted text of those cited passages. Numbers that OCR may have misread are
masked out of the evidence first. Anything else is rejected, never repaired.

Known gap: month names and number words ("ten thousand") are not checked.
"""

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from services.metadata_extraction.critical import mask
from services.metadata_extraction.normalise import extract_amounts, extract_dates, normalise_digits
from services.retrieval.bm25 import Passage


class Claim(BaseModel):
    text: str
    citations: list[str]


class ModelAnswer(BaseModel):
    claims: list[Claim]
    uncertainties: list[str] = []


class MalformedOutput(ValueError):
    pass


@dataclass(frozen=True)
class Rejected:
    claim: Claim
    reason: str


@dataclass(frozen=True)
class Validation:
    accepted: list[Claim]
    rejected: list[Rejected]


def parse(raw: str) -> ModelAnswer:
    try:
        return ModelAnswer.model_validate(json.loads(_strip_fences(raw)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise MalformedOutput(str(exc)) from exc


def _strip_fences(raw: str) -> str:
    """Accept a JSON object wrapped in a ```json fence; reject any other prose."""
    s = raw.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    return m.group(1) if m else s


def trusted_text(p: Passage) -> str:
    return mask(p.text, list(p.untrusted))


def _canonical_citation(citation: str, by_id: dict[str, Passage], aliases: dict[str, str]) -> str | None:
    """Resolve a model-facing evidence label without weakening provenance.

    Exact canonical IDs and explicit aliases are preferred. A shortened suffix
    (for example ``p1:3``) is accepted only when it identifies exactly one of
    the retrieved passages; ambiguous suffixes remain invalid.
    """
    if citation in by_id:
        return citation
    mapped = aliases.get(citation)
    if mapped in by_id:
        return mapped
    matches = [passage_id for passage_id in by_id if passage_id.endswith(f":{citation}")]
    return matches[0] if len(matches) == 1 else None


def validate(answer: ModelAnswer, retrieved: list[Passage], citation_aliases: dict[str, str] | None = None) -> Validation:
    by_id = {p.passage_id: p for p in retrieved}
    aliases = citation_aliases or {}
    accepted, rejected = [], []
    for claim in answer.claims:
        if not claim.citations:
            rejected.append(Rejected(claim, "no citation"))
            continue
        resolved = [_canonical_citation(c, by_id, aliases) for c in claim.citations]
        unknown = [c for c, canonical in zip(claim.citations, resolved) if canonical is None]
        if unknown:
            rejected.append(Rejected(claim, f"citation not in retrieved evidence: {unknown}"))
            continue
        canonical = list(dict.fromkeys(c for c in resolved if c is not None))
        evidence = " ".join(trusted_text(by_id[c]) for c in canonical)
        missing = _unsupported_values(claim.text, evidence)
        if missing:
            rejected.append(Rejected(claim, f"values not found in verified text of cited passages: {missing}"))
            continue
        accepted.append(claim.model_copy(update={"citations": canonical}))
    return Validation(accepted, rejected)


def numbers(text: str) -> set[str]:
    """Digit runs with grouping commas removed and leading zeros stripped."""
    norm = re.sub(r"(?<=\d),(?=\d)", "", normalise_digits(text))
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", norm)}


def _unsupported_values(claim: str, evidence: str) -> list[str]:
    ev_dates = {d.value for d in extract_dates(evidence)}
    ev_amounts = {a.value for a in extract_amounts(evidence)}
    missing = [d.raw for d in extract_dates(claim) if d.value not in ev_dates]
    missing += [a.raw for a in extract_amounts(claim) if a.value not in ev_amounts]
    missing += sorted(numbers(claim) - numbers(evidence), key=int)
    return list(dict.fromkeys(missing))
