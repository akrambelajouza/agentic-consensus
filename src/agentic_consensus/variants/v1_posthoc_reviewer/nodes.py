"""Nodes for the post-hoc reviewer graph."""

from langchain_core.messages import HumanMessage, SystemMessage

from ... import config
from ...models import agent_a_llm, agent_b_llm
from ...usage import usage_from_message
from . import prompts
from .state import PostHocReview, PostHocState

VARIANT_ID = "v1-posthoc-reviewer"
VARIANT_VERSION = 1


def _as_review(value: PostHocReview | dict) -> PostHocReview:
    return (
        value
        if isinstance(value, PostHocReview)
        else PostHocReview.model_validate(value)
    )


def _stalled(reviews: list[PostHocReview]) -> bool:
    patience = config.stall_patience()
    scores = [review.score for review in reviews]
    if len(scores) <= patience:
        return False
    recent = scores[-(patience + 1) :]
    return all(later <= earlier for earlier, later in zip(recent, recent[1:]))


def agent_a(state: PostHocState) -> dict:
    parts = [f"ORIGINAL USER PROBLEM\n{state['problem']}"]
    reviews = state.get("reviews") or []
    if reviews:
        review = _as_review(reviews[-1])
        criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(review.criteria, 1))
        changes = "\n".join(f"- {change}" for change in review.required_changes)
        parts += [
            f"YOUR PREVIOUS PROPOSAL\n{state['proposal']}",
            f"REVIEWER'S POST-HOC CRITERIA\n{criteria}",
            f"REVIEWER'S CRITIQUE (scored {review.score}/10)\n{review.critique}",
            f"REQUIRED CHANGES\n{changes or '- (none listed)'}",
            "Return the full revised answer.",
        ]

    response = agent_a_llm().invoke(
        [SystemMessage(prompts.AGENT_A), HumanMessage("\n\n".join(parts))]
    )
    text = str(response.text)
    return {
        "variant": VARIANT_ID,
        "variant_version": VARIANT_VERSION,
        "max_rounds": state.get("max_rounds") or config.max_rounds(),
        "round": state.get("round", 0) + 1,
        "proposal": text,
        "proposals": [text],
        "usage": [usage_from_message("agent_a", "agent_a", response)],
    }


def agent_b(state: PostHocState) -> dict:
    llm = agent_b_llm().with_structured_output(
        PostHocReview, method="json_schema", include_raw=True
    )
    result = llm.invoke(
        [
            SystemMessage(prompts.AGENT_B),
            HumanMessage(
                f"ORIGINAL USER PROBLEM\n{state['problem']}\n\n"
                f"PROPOSAL TO REVIEW (round {state['round']})\n{state['proposal']}"
            ),
        ]
    )
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    review: PostHocReview = result["parsed"]
    reviews = [_as_review(value) for value in state.get("reviews") or []] + [review]

    update = {
        "criteria": review.criteria,
        "criteria_history": [review.criteria],
        "reviews": [review],
        "usage": [usage_from_message("agent_b", "agent_b", result["raw"])],
    }
    if review.approved:
        update.update(verdict="consensus", final_answer=state["proposal"])
    elif state["round"] >= state["max_rounds"]:
        update.update(verdict="no_consensus", final_answer=state["proposal"])
    elif _stalled(reviews):
        update.update(verdict="stalled", final_answer=state["proposal"])
    return update


__all__ = ["agent_a", "agent_b"]
