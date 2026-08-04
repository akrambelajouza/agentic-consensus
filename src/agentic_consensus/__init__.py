"""Named author/reviewer workflow experiments built on LangGraph.

V1 uses a moderator around an author/reviewer loop; V2 creates its criteria post hoc;
V3 adversarially searches for substantiated defects. Rejected proposals return to
Agent A until the reviewer approves or a stopping rule fires.

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
from .variants import DEFAULT_VARIANT, VARIANTS, get_variant

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
    "DEFAULT_VARIANT",
    "VARIANTS",
    "get_variant",
]
