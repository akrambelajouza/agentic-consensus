"""Registry of independently inspectable consensus graph variants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


V1_MODERATED_CRITERIA = "v1-moderated-criteria"
V2_POSTHOC_REVIEWER = "v2-posthoc-reviewer"
DEFAULT_VARIANT = V1_MODERATED_CRITERIA


@dataclass(frozen=True)
class VariantSpec:
    id: str
    version: int
    label: str
    description: str
    build_graph: Callable[[], object]


def _build_v1():
    from .v1_moderated_criteria.graph import build_graph

    return build_graph()


def _build_v2():
    from .v2_posthoc_reviewer.graph import build_graph

    return build_graph()


VARIANTS = {
    V1_MODERATED_CRITERIA: VariantSpec(
        id=V1_MODERATED_CRITERIA,
        version=1,
        label="V1 — Moderated criteria",
        description=(
            "Moderator fixes criteria before Agent A drafts and Agent B reviews."
        ),
        build_graph=_build_v1,
    ),
    V2_POSTHOC_REVIEWER: VariantSpec(
        id=V2_POSTHOC_REVIEWER,
        version=1,
        label="V2 — Post-hoc reviewer",
        description=(
            "Agent B derives criteria after seeing Agent A's proposal and reviews it "
            "in one call."
        ),
        build_graph=_build_v2,
    ),
}


def get_variant(variant_id: str | None) -> VariantSpec:
    resolved = variant_id or DEFAULT_VARIANT
    try:
        return VARIANTS[resolved]
    except KeyError:
        choices = ", ".join(VARIANTS)
        raise ValueError(
            f"Unknown variant {resolved!r}. Choose one of: {choices}"
        ) from None
