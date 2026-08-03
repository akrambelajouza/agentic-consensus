"""Backward-compatible V1 prompt exports."""

from .variants.v1_moderated_criteria.prompts import (
    AGENT_A,
    AGENT_B,
    FINALIZE_CONSENSUS,
    FINALIZE_NO_CONSENSUS,
    MODERATOR_INTAKE,
)

__all__ = [
    "MODERATOR_INTAKE",
    "AGENT_A",
    "AGENT_B",
    "FINALIZE_CONSENSUS",
    "FINALIZE_NO_CONSENSUS",
]
