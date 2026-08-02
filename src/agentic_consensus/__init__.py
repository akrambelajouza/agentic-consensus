"""A three-agent consensus loop built on LangGraph.

A moderator frames a problem into checkable acceptance criteria, Agent A proposes a
solution, and Agent B reviews it against those criteria. Rejected proposals go back to
Agent A with the critique attached, until Agent B approves or a stopping rule fires.

Everything tunable — the round cap, the stall guard, and each role's model, token
budget, and reasoning effort — is read from the environment. See ``config.py`` and
``.env.example``.

Agents are provider-agnostic: each role is configured with a ``provider:model`` spec
(``anthropic`` or ``openai``), so the author and the critic can run on different
vendors. See ``models.py``.
"""

from . import config
from .config import settings
from .graph import build_graph, graph
from .models import active_models, build_llm, parse_spec, resolve_spec
from .state import ConsensusState, Criteria, Review
from .transcript import render_html, render_json, render_markdown, summary

__all__ = [
    "build_graph",
    "graph",
    "config",
    "settings",
    "ConsensusState",
    "Criteria",
    "Review",
    "active_models",
    "build_llm",
    "parse_spec",
    "resolve_spec",
    "render_html",
    "render_json",
    "render_markdown",
    "summary",
]
