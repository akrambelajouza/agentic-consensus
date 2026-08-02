"""Graph state and the structured schemas the agents return."""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

Verdict = Literal["consensus", "no_consensus", "stalled"]

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


class Review(BaseModel):
    """Agent B's verdict on a proposal."""

    approved: bool = Field(
        description="True only if every acceptance criterion is met."
    )
    score: int = Field(ge=1, le=10, description="Overall quality, 1-10.")
    critique: str = Field(description="What is wrong or missing, and why.")
    required_changes: list[str] = Field(
        default_factory=list,
        description="Specific, actionable changes. Empty when approved.",
    )

    @field_validator("score", mode="before")
    @classmethod
    def _clamp_score(cls, value: object) -> object:
        """Clamp instead of raising on an out-of-range score.

        Anthropic's structured outputs don't support numeric bounds, so LangChain
        strips ``ge``/``le`` from the wire schema and Pydantic enforces them
        client-side. Without this, a stray 11 would raise mid-loop and throw away a
        run that has already spent several Opus calls. The score only drives stall
        detection, so clamping loses nothing.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        return max(1, min(10, int(value)))


class Usage(BaseModel):
    """Token accounting for a single LLM call, for the web UI's per-node metadata.

    ``None`` fields mean the provider didn't report that number, not zero.
    """

    node: str
    role: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ConsensusState(TypedDict, total=False):
    """State threaded through the graph.

    ``proposals`` and ``reviews`` use additive reducers so each round appends to the
    history rather than overwriting it; that history is what ``finalize`` summarises
    over and what makes the Studio trace readable.
    """

    # Inputs.
    problem: str
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
