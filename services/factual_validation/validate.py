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


def validate(answer: ModelAnswer, retrieved: list[Passage]) -> Validation:
    by_id = {p.passage_id: p for p in retrieved}
    accepted, rejected = [], []
    for claim in answer.claims:
        if not claim.citations:
            rejected.append(Rejected(claim, "no citation"))
            continue
        unknown = [c for c in claim.citations if c not in by_id]
        if unknown:
            rejected.append(Rejected(claim, f"citation not in retrieved evidence: {unknown}"))
            continue
        evidence = " ".join(trusted_text(by_id[c]) for c in claim.citations)
        missing = _unsupported_values(claim.text, evidence)
        if missing:
            rejected.append(Rejected(claim, f"values not found in verified text of cited passages: {missing}"))
            continue
        accepted.append(claim)
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
