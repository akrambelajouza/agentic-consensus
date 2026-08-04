"""Nodes for V3's moderated adversarial reviewer graph."""

from langchain_core.messages import HumanMessage, SystemMessage

from ... import config
from ...models import agent_a_llm, agent_b_llm, moderator_llm
from ...usage import usage_from_message
from ..v1_moderated_criteria.state import Criteria
from . import prompts
from .state import AdversarialReview, AdversarialState

VARIANT_ID = "v3-adversarial-reviewer"
VARIANT_VERSION = 1


def _as_review(value: AdversarialReview | dict) -> AdversarialReview:
    return (
        value
        if isinstance(value, AdversarialReview)
        else AdversarialReview.model_validate(value)
    )


def _format_criteria(criteria: list[str]) -> str:
    return "\n".join(f"{i}. {criterion}" for i, criterion in enumerate(criteria, 1))


def _stalled(reviews: list[AdversarialReview]) -> bool:
    """Stop when blocking-defect counts do not fall within the patience window."""
    patience = config.stall_patience()
    counts = [len(review.blocking_findings()) for review in reviews]
    if len(counts) <= patience:
        return False
    recent = counts[-(patience + 1) :]
    return all(later >= earlier for earlier, later in zip(recent, recent[1:]))


def intake(state: AdversarialState) -> dict:
    """Moderator: establish the problem and fixed criteria before drafting."""
    llm = moderator_llm().with_structured_output(
        Criteria, method="json_schema", include_raw=True
    )
    result = llm.invoke(
        [
            SystemMessage(prompts.MODERATOR_INTAKE),
            HumanMessage(f"Problem from the user:\n\n{state['problem']}"),
        ]
    )
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    framing: Criteria = result["parsed"]
    return {
        "variant": VARIANT_ID,
        "variant_version": VARIANT_VERSION,
        "restated_problem": framing.restated_problem,
        "criteria": framing.criteria,
        "round": 0,
        "max_rounds": state.get("max_rounds") or config.max_rounds(),
        "usage": [usage_from_message("intake", "moderator", result["raw"])],
    }


def agent_a(state: AdversarialState) -> dict:
    parts = [
        f"PROBLEM\n{state['restated_problem']}",
        f"FIXED ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}",
    ]
    reviews = state.get("reviews") or []
    if reviews:
        review = _as_review(reviews[-1])
        defects = "\n\n".join(
            f"[{category}]\n"
            f"Defect: {finding.description}\n"
            f"Evidence: {finding.evidence}\n"
            f"Required correction: {finding.required_correction}"
            for category, finding in review.blocking_findings()
        )
        parts += [
            f"YOUR PREVIOUS PROPOSAL\n{state['proposal']}",
            f"SUBSTANTIATED BLOCKING DEFECTS\n{defects}",
            "Return the full revised answer with every blocking defect corrected.",
        ]

    response = agent_a_llm().invoke(
        [SystemMessage(prompts.AGENT_A), HumanMessage("\n\n".join(parts))]
    )
    text = str(response.text)
    return {
        "round": state["round"] + 1,
        "proposal": text,
        "proposals": [text],
        "usage": [usage_from_message("agent_a", "agent_a", response)],
    }


def agent_b(state: AdversarialState) -> dict:
    """Adversarially search for defects against the moderator's fixed criteria."""
    llm = agent_b_llm().with_structured_output(
        AdversarialReview, method="json_schema", include_raw=True
    )
    result = llm.invoke(
        [
            SystemMessage(prompts.AGENT_B),
            HumanMessage(
                f"PROBLEM\n{state['restated_problem']}\n\n"
                f"FIXED ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}\n\n"
                f"PROPOSAL TO REVIEW (round {state['round']})\n{state['proposal']}"
            ),
        ]
    )
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    review = _as_review(result["parsed"])
    return {
        "reviews": [review],
        "usage": [usage_from_message("agent_b", "agent_b", result["raw"])],
    }


def finalize(state: AdversarialState) -> dict:
    """Moderator: derive the verdict and synthesize the user-facing answer."""
    reviews = [_as_review(value) for value in state.get("reviews") or []]
    latest = reviews[-1] if reviews else None
    if latest is not None and latest.approved:
        verdict = "consensus"
        system = prompts.FINALIZE_CONSENSUS
        outcome = "Agent B found no substantiated blocking defects."
    elif state["round"] >= state["max_rounds"]:
        verdict = "no_consensus"
        system = prompts.FINALIZE_NO_CONSENSUS
        outcome = f"The round limit ({state['max_rounds']}) was reached."
    else:
        verdict = "stalled"
        system = prompts.FINALIZE_NO_CONSENSUS
        outcome = "The number of blocking defects stopped decreasing."

    history_parts = []
    for number, (proposal, review) in enumerate(
        zip(state.get("proposals") or [], reviews), start=1
    ):
        findings = "\n".join(
            f"- [{finding.severity}] {category}: {finding.description}; "
            f"evidence: {finding.evidence}; correction: {finding.required_correction}"
            for category, group in review.categorized_findings()
            for finding in group
        ) or "- No defects reported."
        history_parts.append(
            f"--- ROUND {number} PROPOSAL ---\n{proposal}\n\n"
            f"--- ROUND {number} ADVERSARIAL REVIEW ---\n{review.summary}\n{findings}"
        )

    response = moderator_llm().invoke(
        [
            SystemMessage(system),
            HumanMessage(
                f"PROBLEM\n{state['restated_problem']}\n\n"
                f"FIXED ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}\n\n"
                f"OUTCOME\n{outcome}\n\n"
                f"FULL HISTORY\n{'\n\n'.join(history_parts)}"
            ),
        ]
    )
    return {
        "verdict": verdict,
        "final_answer": str(response.text),
        "usage": [usage_from_message("finalize", "moderator", response)],
    }


__all__ = ["agent_a", "agent_b", "finalize", "intake"]
