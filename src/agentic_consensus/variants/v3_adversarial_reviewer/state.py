"""State and structured findings for the adversarial reviewer variant."""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, computed_field, model_validator

from ...schemas import Usage, Verdict

Severity = Literal["blocking", "non_blocking", "speculative"]


class Defect(BaseModel):
    """One evidence-backed reason a proposal may not be ready."""

    description: str = Field(min_length=1, description="The concrete defect or concern.")
    severity: Severity = Field(
        description=(
            "blocking only when the proposal must change; non_blocking for useful "
            "improvements; speculative when evidence is insufficient."
        )
    )
    evidence: str = Field(
        min_length=1,
        description="Specific evidence from the original problem or proposal."
    )
    required_correction: str = Field(
        description="A concrete correction; empty when the finding is speculative."
    )

    @model_validator(mode="after")
    def _actionable_when_substantiated(self) -> "Defect":
        if self.severity != "speculative" and not self.required_correction.strip():
            raise ValueError("substantiated findings require a correction")
        return self


class AdversarialReview(BaseModel):
    """A defect inventory whose blocking findings determine the verdict."""

    missing_requirements: list[Defect] = Field(default_factory=list)
    violated_acceptance_criteria: list[Defect] = Field(default_factory=list)
    edge_cases: list[Defect] = Field(default_factory=list)
    ambiguities: list[Defect] = Field(default_factory=list)
    risks: list[Defect] = Field(default_factory=list)
    summary: str = Field(
        description="Concise conclusion grounded in the reported findings."
    )

    def categorized_findings(self) -> list[tuple[str, list[Defect]]]:
        return [
            ("Missing requirements", self.missing_requirements),
            ("Violated acceptance criteria", self.violated_acceptance_criteria),
            ("Edge cases", self.edge_cases),
            ("Ambiguities", self.ambiguities),
            ("Risks", self.risks),
        ]

    def blocking_findings(self) -> list[tuple[str, Defect]]:
        return [
            (category, finding)
            for category, findings in self.categorized_findings()
            for finding in findings
            if finding.severity == "blocking"
        ]

    @computed_field(return_type=bool)
    @property
    def approved(self) -> bool:
        """Approval is derived, never trusted as an independent model claim."""
        return not self.blocking_findings()

    @computed_field(return_type=list[str])
    @property
    def required_changes(self) -> list[str]:
        return [finding.required_correction for _, finding in self.blocking_findings()]


class AdversarialState(TypedDict, total=False):
    problem: str
    variant: str
    variant_version: int
    max_rounds: int

    # Fixed by the moderator before Agent A drafts.
    restated_problem: str
    criteria: list[str]

    round: int
    proposal: str
    proposals: Annotated[list[str], operator.add]
    reviews: Annotated[list[AdversarialReview], operator.add]
    verdict: Verdict
    final_answer: str
    usage: Annotated[list[Usage], operator.add]


__all__ = ["AdversarialReview", "AdversarialState", "Defect", "Severity"]
