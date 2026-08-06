"""V1 graph: answer first, then derive criteria and review in one call."""

from langgraph.graph import END, START, StateGraph

from .nodes import agent_a, agent_b
from .state import PostHocState


def route(state: PostHocState) -> str:
    return "end" if state.get("verdict") else "agent_a"


def build_graph():
    builder = StateGraph(PostHocState)
    builder.add_node("agent_a", agent_a)
    builder.add_node("agent_b", agent_b)
    builder.add_edge(START, "agent_a")
    builder.add_edge("agent_a", "agent_b")
    builder.add_conditional_edges(
        "agent_b",
        route,
        {"agent_a": "agent_a", "end": END},
    )
    return builder.compile()


graph = build_graph()

__all__ = ["build_graph", "graph", "route"]
