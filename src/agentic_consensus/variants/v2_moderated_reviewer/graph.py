"""Graph wiring.

    START -> intake -> agent_a -> agent_b -> [route]
                          ^                     |
                          +------ revise -------+
                                                v
                                            finalize -> END

Routing is a plain conditional edge, not an LLM call. Agent B already returns
`approved: bool`; asking a fourth model "should we loop again?" would add a round
trip, cost, and a failure mode for no information.
"""

from langgraph.graph import END, START, StateGraph

from ... import config
from .nodes import agent_a, agent_b, finalize, intake
from .state import ConsensusState, Review


def _scores(state: ConsensusState) -> list[int]:
    reviews = state.get("reviews") or []
    return [
        (r if isinstance(r, Review) else Review.model_validate(r)).score for r in reviews
    ]


def _stalled(state: ConsensusState) -> bool:
    """True when the score has failed to improve for ``STALL_PATIENCE`` rounds running.

    Guards against a critic that keeps re-scoring 6/10 with the same complaint —
    without this, an unsatisfiable criterion burns every remaining round.
    """
    patience = config.stall_patience()
    scores = _scores(state)
    if len(scores) <= patience:
        return False
    recent = scores[-(patience + 1) :]
    return all(later <= earlier for earlier, later in zip(recent, recent[1:]))


def route(state: ConsensusState) -> str:
    """Decide whether to loop back to Agent A or wrap up.

    ``finalize`` derives the verdict itself from the same signals, so this function
    only picks a destination.
    """
    reviews = state.get("reviews") or []
    latest = reviews[-1]
    latest = latest if isinstance(latest, Review) else Review.model_validate(latest)

    if latest.approved:
        return "finalize"
    if state["round"] >= state["max_rounds"]:
        return "finalize"
    if _stalled(state):
        return "finalize"
    return "agent_a"


def build_graph():
    """Build and compile the consensus graph."""
    builder = StateGraph(ConsensusState)

    builder.add_node("intake", intake)
    builder.add_node("agent_a", agent_a)
    builder.add_node("agent_b", agent_b)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "agent_a")
    builder.add_edge("agent_a", "agent_b")
    builder.add_conditional_edges(
        "agent_b",
        route,
        {"agent_a": "agent_a", "finalize": "finalize"},
    )
    builder.add_edge("finalize", END)

    return builder.compile()


graph = build_graph()
