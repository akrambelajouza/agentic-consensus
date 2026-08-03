"""Structured schemas shared by every workflow variant."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Verdict = Literal["consensus", "no_consensus", "stalled"]


class Review(BaseModel):
    """Common reviewer verdict; variants may extend it with more evidence."""

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
        """Clamp provider output before Pydantic applies the 1-10 bounds."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        return max(1, min(10, int(value)))


class Usage(BaseModel):
    """Token and cost accounting for one model call."""

    node: str
    role: str
    provider: str
    model: str
    generation_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost: float | None = None
    upstream_inference_cost: float | None = None
    cost_source: Literal["provider_reported", "estimated", "unavailable"] = (
        "unavailable"
    )


__all__ = ["Review", "Usage", "Verdict"]
