"""Validates SLM output against the passages it cites (Workstream C, plan §4).

A claim survives only if it cites at least one passage that was actually
retrieved, and every date and rupee amount it states appears in those cited
passages. Anything else is rejected, never repaired.
"""

import json
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from services.metadata_extraction.normalise import extract_amounts, extract_dates
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
        return ModelAnswer.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise MalformedOutput(str(exc)) from exc


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
        evidence = " ".join(by_id[c].text for c in claim.citations)
        missing = _unsupported_values(claim.text, evidence)
        if missing:
            rejected.append(Rejected(claim, f"values not found in cited passages: {missing}"))
            continue
        accepted.append(claim)
    return Validation(accepted, rejected)


def _unsupported_values(claim: str, evidence: str) -> list[str]:
    ev_dates = {d.value for d in extract_dates(evidence)}
    ev_amounts = {a.value for a in extract_amounts(evidence)}
    missing = [d.raw for d in extract_dates(claim) if d.value not in ev_dates]
    missing += [a.raw for a in extract_amounts(claim) if a.value not in ev_amounts]
    return missing
