"""Graph state and structured schemas for V1's moderated-criteria workflow."""

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from ...schemas import Review, Usage, Verdict

# Tunables (round cap, stall patience, per-role models and budgets) are not constants
# here: they live in `config.py` and are read from the environment. See `.env.example`.


class Criteria(BaseModel):
    """The moderator's framing of what a good answer must satisfy."""

    restated_problem: str = Field(
        description="The problem restated in one precise paragraph."
    )
    criteria: list[str] = Field(
        description="3-6 concrete, independently checkable acceptance criteria."
    )


class ConsensusState(TypedDict, total=False):
    """State threaded through the graph.

    ``proposals`` and ``reviews`` use additive reducers so each round appends to the
    history rather than overwriting it; that history is what ``finalize`` summarises
    over and what makes the Studio trace readable.
    """

    # Inputs.
    problem: str
    variant: str
    variant_version: int
    max_rounds: int

    # Set by the moderator at intake.
    restated_problem: str
    criteria: list[str]

    # Loop bookkeeping.
    round: int
    proposal: str
    proposals: Annotated[list[str], operator.add]
    reviews: Annotated[list[Review], operator.add]

    # Set by finalize.
    verdict: Verdict
    final_answer: str

    # Per-call token accounting, one entry per node execution. Additive for the same
    # reason as `proposals`/`reviews`: the web UI wants the full history, not just the
    # latest call.
    usage: Annotated[list[Usage], operator.add]
