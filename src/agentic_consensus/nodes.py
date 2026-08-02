"""The four graph nodes.

Each node takes the state and returns only the keys it changes.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from . import config, prompts
from .models import agent_a_llm, agent_b_llm, moderator_llm
from .state import ConsensusState, Criteria, Review


def _as_review(value: Review | dict) -> Review:
    """Reviews come back from the model as ``Review`` but round-trip through the
    checkpointer as plain dicts. Normalise so callers never have to care."""
    return value if isinstance(value, Review) else Review.model_validate(value)


def _latest_review(state: ConsensusState) -> Review | None:
    reviews = state.get("reviews") or []
    return _as_review(reviews[-1]) if reviews else None


def _format_criteria(criteria: list[str]) -> str:
    return "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, start=1))


def intake(state: ConsensusState) -> dict:
    """Moderator: turn the raw problem into a restated statement and criteria."""
    llm = moderator_llm().with_structured_output(Criteria, method="json_schema")
    framing: Criteria = llm.invoke(
        [
            SystemMessage(prompts.MODERATOR_INTAKE),
            HumanMessage(f"Problem from the user:\n\n{state['problem']}"),
        ]
    )
    return {
        "restated_problem": framing.restated_problem,
        "criteria": framing.criteria,
        "round": 0,
        "max_rounds": state.get("max_rounds") or config.max_rounds(),
    }


def agent_a(state: ConsensusState) -> dict:
    """Agent A: produce a complete solution, revising if there is a critique."""
    parts = [
        f"PROBLEM\n{state['restated_problem']}",
        f"ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}",
    ]

    review = _latest_review(state)
    if review is not None:
        # Round 2+. Omit this block entirely on the first pass rather than sending
        # placeholder text the model has to interpret.
        changes = "\n".join(f"- {c}" for c in review.required_changes) or "- (none listed)"
        parts += [
            f"YOUR PREVIOUS PROPOSAL\n{state['proposal']}",
            f"REVIEWER'S CRITIQUE (scored {review.score}/10)\n{review.critique}",
            f"REQUIRED CHANGES\n{changes}",
            "Revise your proposal to address every required change. "
            "Output the full revised solution, not a description of your edits.",
        ]

    # `.text` is a str subclass (TextAccessor); coerce so what lands in state and the
    # checkpointer is a plain str.
    text = str(
        agent_a_llm()
        .invoke([SystemMessage(prompts.AGENT_A), HumanMessage("\n\n".join(parts))])
        .text
    )

    return {
        "round": state["round"] + 1,
        "proposal": text,
        "proposals": [text],
    }


def agent_b(state: ConsensusState) -> dict:
    """Agent B: grade the current proposal against the criteria."""
    llm = agent_b_llm().with_structured_output(Review, method="json_schema")
    review: Review = llm.invoke(
        [
            SystemMessage(prompts.AGENT_B),
            HumanMessage(
                f"PROBLEM\n{state['restated_problem']}\n\n"
                f"ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}\n\n"
                f"PROPOSAL TO REVIEW (round {state['round']})\n{state['proposal']}"
            ),
        ]
    )
    return {"reviews": [review]}


def finalize(state: ConsensusState) -> dict:
    """Moderator: derive the verdict and write the user-facing answer.

    The verdict is derived here rather than in the router so there is exactly one
    place that decides how a run is characterised.
    """
    reviews = [_as_review(r) for r in state.get("reviews") or []]
    latest = reviews[-1] if reviews else None

    if latest is not None and latest.approved:
        verdict = "consensus"
        system = prompts.FINALIZE_CONSENSUS
    elif state["round"] >= state["max_rounds"]:
        verdict = "no_consensus"
        system = prompts.FINALIZE_NO_CONSENSUS
    else:
        verdict = "stalled"
        system = prompts.FINALIZE_NO_CONSENSUS

    history = "\n\n".join(
        f"--- ROUND {i} PROPOSAL ---\n{proposal}\n\n"
        f"--- ROUND {i} REVIEW ---\n"
        f"approved={review.approved} score={review.score}/10\n"
        f"{review.critique}"
        + (
            "\nOutstanding: " + "; ".join(review.required_changes)
            if review.required_changes
            else ""
        )
        for i, (proposal, review) in enumerate(
            zip(state.get("proposals") or [], reviews), start=1
        )
    )

    outcome = {
        "consensus": "Agent B approved the final proposal.",
        "no_consensus": (
            f"The round limit ({state['max_rounds']}) was reached without approval."
        ),
        "stalled": (
            "The review stalled: the score stopped improving while the proposal "
            "remained unapproved."
        ),
    }[verdict]

    text = str(
        moderator_llm()
        .invoke(
            [
                SystemMessage(system),
                HumanMessage(
                    f"PROBLEM\n{state['restated_problem']}\n\n"
                    f"ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}\n\n"
                    f"OUTCOME\n{outcome}\n\n"
                    f"FULL HISTORY\n{history}"
                ),
            ]
        )
        .text
    )

    return {"verdict": verdict, "final_answer": text}
