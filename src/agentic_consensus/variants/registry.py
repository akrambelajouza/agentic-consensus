"""Registry of independently inspectable consensus graph variants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


V2_MODERATED_REVIEWER = "v2-moderated-reviewer"
V1_POSTHOC_REVIEWER = "v1-posthoc-reviewer"
V3_ADVERSARIAL_REVIEWER = "v3-adversarial-reviewer"
DEFAULT_VARIANT = V1_POSTHOC_REVIEWER


@dataclass(frozen=True)
class VariantSpec:
    id: str
    version: int
    label: str
    description: str
    build_graph: Callable[[], object]


def _build_v1():
    from .v1_posthoc_reviewer.graph import build_graph

    return build_graph()


def _build_v2():
    from .v2_moderated_reviewer.graph import build_graph

    return build_graph()


def _build_v3():
    from .v3_adversarial_reviewer.graph import build_graph

    return build_graph()


VARIANTS = {
    V1_POSTHOC_REVIEWER: VariantSpec(
        id=V1_POSTHOC_REVIEWER,
        version=1,
        label="V1 — Post-hoc reviewer",
        description=(
            "Agent B derives criteria after seeing Agent A's proposal and reviews it "
            "in one call."
        ),
        build_graph=_build_v1,
    ),
    V2_MODERATED_REVIEWER: VariantSpec(
        id=V2_MODERATED_REVIEWER,
        version=1,
        label="V2 — Moderated reviewer",
        description=(
            "Moderator fixes criteria before Agent A drafts and Agent B reviews."
        ),
        build_graph=_build_v2,
    ),
    V3_ADVERSARIAL_REVIEWER: VariantSpec(
        id=V3_ADVERSARIAL_REVIEWER,
        version=1,
        label="V3 — Adversarial reviewer",
        description=(
            "Moderator fixes criteria before Agent A drafts; Agent B then tries to "
            "prove the proposal is not ready through substantiated blocking defects."
        ),
        build_graph=_build_v3,
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
