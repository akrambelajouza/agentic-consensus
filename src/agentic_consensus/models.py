"""Model factories for the three roles, with pluggable providers.

Each role is configured by a ``provider:model`` spec plus a token budget and a
reasoning effort, all of them environment variables — see ``config.py`` for the full
table. Nothing here is hardcoded; this module only turns resolved settings into chat
model instances.

Three providers are supported: ``anthropic`` and ``openai`` talk to the vendor APIs
directly, and ``openrouter`` reaches both (and everything else it routes) through a
single key — useful when you don't hold accounts with the vendors themselves::

    AGENT_A_MODEL=openrouter:anthropic/claude-opus-5
    AGENT_B_MODEL=openrouter:openai/gpt-5.5

Mixing providers is supported and is arguably the point — running the critic on a
different vendor than the author is the strongest version of the "reviewer shouldn't
share the author's blind spots" argument.

Every integration exposes the two knobs this project needs — ``reasoning_effort`` and
``with_structured_output(..., method="json_schema")`` — so the graph code never has to
branch on provider.

Never set ``temperature``/``top_p``/``top_k``: Claude Opus 5 and Sonnet 5 reject
non-default sampling parameters outright, and OpenAI reasoning models ignore them.
Steer behaviour through the prompts and effort instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import config
from .config import DEFAULT_MODELS

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

SUPPORTED_PROVIDERS = ("anthropic", "openai", "openrouter")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# OpenAI accepts minimal/low/medium/high; Anthropic accepts low/medium/high/xhigh/max.
# Map each one's unsupported levels onto the nearest neighbour it does accept, so
# swapping a role's provider never fails on an effort value. OpenRouter accepts every
# level this project allows, so it needs no map.
_EFFORT_MAPS: dict[str, dict[str, str]] = {
    "openai": {"xhigh": "high", "max": "high"},
    "anthropic": {"minimal": "low"},
    "openrouter": {},
}


def _infer_provider(model: str) -> str:
    """Best-effort provider guess for a spec written without an explicit prefix."""
    # OpenRouter IDs are namespaced (`anthropic/claude-opus-5`); no direct vendor API
    # uses a slash, so this is unambiguous.
    if "/" in model:
        return "openrouter"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    raise ValueError(
        f"Cannot infer a provider from model {model!r}. "
        f"Write the spec as 'provider:model' using one of {SUPPORTED_PROVIDERS}, "
        f"e.g. 'anthropic:claude-opus-5' or 'openrouter:anthropic/claude-opus-5'."
    )


def parse_spec(spec: str) -> tuple[str, str]:
    """Split a ``provider:model`` spec into its parts.

    A bare model name is accepted and the provider inferred, so ``claude-opus-5``,
    ``anthropic:claude-opus-5`` and ``anthropic/claude-opus-5`` all work.

    Only a *known* provider name before the colon counts as a prefix. That keeps
    OpenRouter IDs that carry their own colon suffix — ``anthropic/claude-sonnet-5:batch``
    — from being misread as provider ``anthropic/claude-sonnet-5``.
    """
    spec = spec.strip()
    if not spec:
        raise ValueError("Model spec is empty.")

    head, sep, tail = spec.partition(":")
    if sep and head.strip().lower() in SUPPORTED_PROVIDERS:
        provider, model = head.strip().lower(), tail.strip()
        if not model:
            raise ValueError(f"Model spec {spec!r} has a provider but no model name.")
        return provider, model

    try:
        return _infer_provider(spec), spec
    except ValueError:
        if sep:
            raise ValueError(
                f"Unsupported provider {head.strip().lower()!r} in spec {spec!r}. "
                f"Supported: {', '.join(SUPPORTED_PROVIDERS)}."
            ) from None
        raise


def resolve_spec(role: str) -> str:
    """The active ``provider:model`` spec for a role, honouring the env override."""
    return config.model_spec(role)


def build_llm(
    role: str, *, max_tokens: int | None = None, effort: str | None = None
) -> BaseChatModel:
    """Instantiate the chat model for a role.

    ``max_tokens`` and ``effort`` default to the role's configured values; pass them
    explicitly only to override the environment for a single call.

    Imports are deferred so that installing only one provider's package is enough,
    and so importing this module never requires an API key — LangGraph Studio imports
    the graph at startup, before any credentials are needed.
    """
    provider, model = parse_spec(resolve_spec(role))
    budget = config.max_tokens(role) if max_tokens is None else max_tokens
    level = config.effort(role) if effort is None else effort
    level = _EFFORT_MAPS[provider].get(level, level)

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ImportError(
                "The 'anthropic' provider needs langchain-anthropic. "
                "Install it with: uv add langchain-anthropic"
            ) from exc
        return ChatAnthropic(model=model, max_tokens=budget, reasoning_effort=level)

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ImportError(
            f"The {provider!r} provider needs langchain-openai. "
            f"Install it with: uv sync --extra {provider}"
        ) from exc

    if provider == "openai":
        return ChatOpenAI(model=model, max_tokens=budget, reasoning_effort=level)

    # OpenRouter speaks the OpenAI wire format, so the same client works against a
    # different base URL. `require_parameters` restricts routing to backends that
    # honour everything we send — without it a request can land on an endpoint with
    # no `response_format` support and fail, since structured output is per-endpoint
    # rather than per-model.
    #
    # `ignore` covers the case `require_parameters` can't: a backend that lists a
    # parameter in its endpoint metadata but rejects it at request time. Azure does
    # exactly that for `structured_outputs`, which is why it's excluded by default.
    from . import runtime_settings

    api_key = runtime_settings.value("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Add it to .env — the 'openrouter' "
            "provider does not fall back to OPENAI_API_KEY."
        )
    routing: dict[str, object] = {"require_parameters": True}
    ignored = config.openrouter_ignore_providers()
    if ignored:
        routing["ignore"] = ignored
    return ChatOpenAI(
        model=model,
        reasoning_effort=level,
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        # ChatOpenAI 1.4 rewrites its `max_tokens` argument to
        # `max_completion_tokens`. OpenRouter capability metadata distinguishes the
        # two names, and many non-OpenAI endpoints (including Gemini) advertise only
        # `max_tokens`; with `require_parameters` enabled the rewritten name filters
        # every endpoint out. Put the OpenRouter wire name in `extra_body` so the
        # client preserves it verbatim.
        extra_body={"max_tokens": budget, "provider": routing},
    )


def moderator_llm() -> BaseChatModel:
    """Frames the problem at intake and synthesises the outcome at the end."""
    return build_llm("moderator")


def agent_a_llm() -> BaseChatModel:
    """The author. Gets the largest budget by default — it writes the deliverable."""
    return build_llm("agent_a")


def agent_b_llm() -> BaseChatModel:
    """The critic."""
    return build_llm("agent_b")


def evaluator_llm() -> BaseChatModel:
    """Independent, rubric-based judge used only after an experiment completes."""
    return build_llm("evaluator")


def active_models() -> dict[str, str]:
    """Resolved spec per role — handy for logging and for transcript headers."""
    return {
        role: resolve_spec(role)
        for role in DEFAULT_MODELS
        if role != "evaluator"
    }
