"""The four graph nodes.

Each node takes the state and returns only the keys it changes.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from . import config, prompts
from .models import agent_a_llm, agent_b_llm, moderator_llm, parse_spec
from .state import ConsensusState, Criteria, Review, Usage


def _as_review(value: Review | dict) -> Review:
    """Reviews come back from the model as ``Review`` but round-trip through the
    checkpointer as plain dicts. Normalise so callers never have to care."""
    return value if isinstance(value, Review) else Review.model_validate(value)


def _usage(node: str, role: str, message) -> Usage:
    """Pull token and cost accounting off a response message.

    LangChain's normalized ``usage_metadata`` provides provider-neutral token counts.
    OpenRouter's exact billed cost remains in the raw ``token_usage`` response
    metadata, so merge both views rather than estimating cost from a price table.
    Missing values stay ``None`` so the UI can distinguish "not reported" from zero.
    """
    meta = getattr(message, "usage_metadata", None) or {}
    response_meta = getattr(message, "response_metadata", None) or {}
    raw = response_meta.get("token_usage") or {}
    input_details = meta.get("input_token_details") or {}
    output_details = meta.get("output_token_details") or {}
    prompt_details = raw.get("prompt_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or {}
    cost_details = raw.get("cost_details") or {}
    spec = config.model_spec(role)
    provider, _ = parse_spec(spec)

    def first(*values):
        return next((value for value in values if value is not None), None)

    cost = raw.get("cost")
    return Usage(
        node=node,
        role=role,
        provider=provider,
        model=spec,
        generation_id=response_meta.get("id"),
        input_tokens=meta.get("input_tokens"),
        output_tokens=meta.get("output_tokens"),
        total_tokens=meta.get("total_tokens"),
        reasoning_tokens=first(
            output_details.get("reasoning"),
            output_details.get("priority_reasoning"),
            output_details.get("flex_reasoning"),
            completion_details.get("reasoning_tokens"),
        ),
        cached_input_tokens=first(
            input_details.get("cache_read"),
            input_details.get("priority_cache_read"),
            input_details.get("flex_cache_read"),
            prompt_details.get("cached_tokens"),
        ),
        cache_write_tokens=first(
            input_details.get("cache_creation"),
            input_details.get("priority_cache_creation"),
            input_details.get("flex_cache_creation"),
            prompt_details.get("cache_write_tokens"),
        ),
        cost=cost,
        upstream_inference_cost=cost_details.get("upstream_inference_cost"),
        cost_source="provider_reported" if cost is not None else "unavailable",
    )


def _latest_review(state: ConsensusState) -> Review | None:
    reviews = state.get("reviews") or []
    return _as_review(reviews[-1]) if reviews else None


def _format_criteria(criteria: list[str]) -> str:
    return "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, start=1))


def intake(state: ConsensusState) -> dict:
    """Moderator: turn the raw problem into a restated statement and criteria."""
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
        "restated_problem": framing.restated_problem,
        "criteria": framing.criteria,
        "round": 0,
        "max_rounds": state.get("max_rounds") or config.max_rounds(),
        "usage": [_usage("intake", "moderator", result["raw"])],
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

    response = agent_a_llm().invoke(
        [SystemMessage(prompts.AGENT_A), HumanMessage("\n\n".join(parts))]
    )
    # `.text` is a str subclass (TextAccessor); coerce so what lands in state and the
    # checkpointer is a plain str.
    text = str(response.text)

    return {
        "round": state["round"] + 1,
        "proposal": text,
        "proposals": [text],
        "usage": [_usage("agent_a", "agent_a", response)],
    }


def agent_b(state: ConsensusState) -> dict:
    """Agent B: grade the current proposal against the criteria."""
    llm = agent_b_llm().with_structured_output(
        Review, method="json_schema", include_raw=True
    )
    result = llm.invoke(
        [
            SystemMessage(prompts.AGENT_B),
            HumanMessage(
                f"PROBLEM\n{state['restated_problem']}\n\n"
                f"ACCEPTANCE CRITERIA\n{_format_criteria(state['criteria'])}\n\n"
                f"PROPOSAL TO REVIEW (round {state['round']})\n{state['proposal']}"
            ),
        ]
    )
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    review: Review = result["parsed"]
    return {
        "reviews": [review],
        "usage": [_usage("agent_b", "agent_b", result["raw"])],
    }


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

    response = moderator_llm().invoke(
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
    text = str(response.text)

    return {
        "verdict": verdict,
        "final_answer": text,
        "usage": [_usage("finalize", "moderator", response)],
    }
