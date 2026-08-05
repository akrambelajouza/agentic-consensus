"""Blind, rubric-based evaluation of experiment outputs."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import evaluator_llm
from .schemas import Usage
from .usage import usage_from_message


class CriterionAssessment(BaseModel):
    criterion_id: str = Field(description="The supplied criterion ID, unchanged.")
    status: Literal["satisfied", "partial", "violated"]
    evidence: str = Field(description="Specific evidence from the response.")
    explanation: str = Field(description="Why the evidence supports this status.")


class EvaluationResult(BaseModel):
    criteria: list[CriterionAssessment]
    summary: str


def normalize_criteria(raw: str | None) -> list[dict[str, str]]:
    """Normalize one criterion per line and assign stable IDs."""
    lines = []
    for line in (raw or "").splitlines():
        text = re.sub(r"^\s*(?:[-*•]+)\s*", "", line).strip()
        if text:
            lines.append(text)
    return [{"id": f"C{index}", "text": text} for index, text in enumerate(lines, 1)]


def validate_result(
    result: EvaluationResult, criteria: list[dict[str, str]]
) -> EvaluationResult:
    expected = [criterion["id"] for criterion in criteria]
    received = [item.criterion_id for item in result.criteria]
    if len(received) != len(set(received)):
        raise ValueError("evaluator returned duplicate criterion IDs")
    if set(received) != set(expected):
        raise ValueError("evaluator omitted or invented criterion IDs")
    by_id = {item.criterion_id: item for item in result.criteria}
    result.criteria = [by_id[criterion_id] for criterion_id in expected]
    return result


def metrics(result: EvaluationResult) -> dict[str, Any]:
    weights = {"satisfied": 1.0, "partial": 0.5, "violated": 0.0}
    count = len(result.criteria)
    coverage = sum(weights[item.status] for item in result.criteria) / count if count else 0
    return {
        "coverage": coverage,
        "passed": bool(count) and all(item.status == "satisfied" for item in result.criteria),
    }


def evaluate_response(
    problem: str, criteria: list[dict[str, str]], final_response: str
) -> tuple[EvaluationResult, Usage]:
    """Evaluate one anonymized answer without architecture or run metadata."""
    rubric = "\n".join(f'{item["id"]}: {item["text"]}' for item in criteria)
    prompt = f"""You are an independent evaluator. Judge only the response against the
given problem and criteria. For every criterion, return its exact ID, one of
satisfied/partial/violated, concise evidence from the response, and an explanation.
Do not infer requirements that are absent from the problem or criteria.

PROBLEM
{problem}

CRITERIA
{rubric}

RESPONSE
{final_response}"""
    structured = evaluator_llm().with_structured_output(
        EvaluationResult, method="json_schema", include_raw=True
    )
    payload = structured.invoke(prompt)
    result = validate_result(payload["parsed"], criteria)
    usage = usage_from_message("evaluation", "evaluator", payload["raw"])
    return result, usage


__all__ = [
    "CriterionAssessment", "EvaluationResult", "evaluate_response", "metrics",
    "normalize_criteria", "validate_result",
]
