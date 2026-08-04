"""V3 graph: fixed moderator criteria plus an adversarial reviewer."""

from langgraph.graph import END, START, StateGraph

from .nodes import _as_review, _stalled, agent_a, agent_b, finalize, intake
from .state import AdversarialState


def route(state: AdversarialState) -> str:
    reviews = [_as_review(value) for value in state.get("reviews") or []]
    latest = reviews[-1]
    if latest.approved:
        return "finalize"
    if state["round"] >= state["max_rounds"]:
        return "finalize"
    if _stalled(reviews):
        return "finalize"
    return "agent_a"


def build_graph():
    builder = StateGraph(AdversarialState)
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

__all__ = ["build_graph", "graph", "route"]
