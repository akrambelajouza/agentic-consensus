"""State and structured review schema for the post-hoc reviewer variant."""

import operator
from typing import Annotated, TypedDict

from pydantic import Field

from ...schemas import Review, Usage, Verdict


class PostHocReview(Review):
    """Criteria derived from the user problem and the verdict against them."""

    criteria: list[str] = Field(
        description="3-6 concrete criteria derived from the original user problem."
    )


class PostHocState(TypedDict, total=False):
    problem: str
    variant: str
    variant_version: int
    max_rounds: int
    round: int
    proposal: str
    proposals: Annotated[list[str], operator.add]
    criteria: list[str]
    criteria_history: Annotated[list[list[str]], operator.add]
    reviews: Annotated[list[PostHocReview], operator.add]
    verdict: Verdict
    final_answer: str
    usage: Annotated[list[Usage], operator.add]


__all__ = ["PostHocReview", "PostHocState"]
