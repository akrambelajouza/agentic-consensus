"""Runtime configuration, all of it environment-driven.

Every tunable in the project is read from the environment through this module, so
`.env` is the single place to change behaviour — no source edits, and the same
settings apply whether you run the CLI, LangGraph Studio, or the library.

===============================  =========  ==================================
Variable                         Default    Effect
===============================  =========  ==================================
``MAX_ROUNDS``                   ``4``      A/B rounds before giving up
``STALL_PATIENCE``               ``2``      Non-improving reviews that stall
``MODERATOR_MODEL``              see below  ``provider:model`` spec
``AGENT_A_MODEL``                see below  ``provider:model`` spec
``AGENT_B_MODEL``                see below  ``provider:model`` spec
``MODERATOR_MAX_TOKENS``         ``8000``   Output cap for the moderator
``AGENT_A_MAX_TOKENS``           ``16000``  Output cap for the author
``AGENT_B_MAX_TOKENS``           ``8000``   Output cap for the reviewer
``MODERATOR_EFFORT``             ``high``   ``reasoning_effort`` for the moderator
``AGENT_A_EFFORT``               ``high``   ``reasoning_effort`` for the author
``AGENT_B_EFFORT``               ``high``   ``reasoning_effort`` for the reviewer
``OPENROUTER_IGNORE_PROVIDERS``  ``Azure``  Backends kept out of OpenRouter routing
``CONSENSUS_DB_PATH``            see below  SQLite file for the web UI's run history
===============================  =========  ==================================

Values are read on each access rather than frozen at import, so a test or a notebook
can change one with ``monkeypatch.setenv`` without reimporting the package.

Bad values fail loudly at startup with the variable name in the message. A silent
fallback to the default would be worse: you would pay for a full run before noticing
that ``MAX_ROUNDS=four`` did nothing.
"""

from __future__ import annotations

import os

# Role -> default `provider:model` spec.
DEFAULT_MODELS: dict[str, str] = {
    "moderator": "anthropic:claude-opus-5",
    "agent_a": "anthropic:claude-opus-5",
    "agent_b": "anthropic:claude-sonnet-5",
}

# Role -> env var prefix. Every per-role setting is `<PREFIX>_<SETTING>`.
ROLE_PREFIXES: dict[str, str] = {
    "moderator": "MODERATOR",
    "agent_a": "AGENT_A",
    "agent_b": "AGENT_B",
}

DEFAULT_MAX_ROUNDS = 4

# Consecutive non-improving reviews that count as a stall.
DEFAULT_STALL_PATIENCE = 2

# Agent A gets double: it writes the full deliverable every round, while the other
# two roles emit a short structured object or a synthesis.
DEFAULT_MAX_TOKENS: dict[str, int] = {
    "moderator": 8_000,
    "agent_a": 16_000,
    "agent_b": 8_000,
}

DEFAULT_EFFORT = "high"

# OpenRouter backends to keep out of routing. Azure advertises `structured_outputs`
# in its endpoint metadata but rejects the request with "structured_outputs not
# supported in your workspace", so `require_parameters` can't filter it out and every
# structured node (`intake`, `agent_b`) fails whenever routing lands there.
DEFAULT_OPENROUTER_IGNORE_PROVIDERS = ("Azure",)

# Union of both providers' vocabularies. `models.py` maps whichever levels the
# target provider doesn't accept onto its nearest supported neighbour.
VALID_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")

DEFAULT_DB_PATH = "consensus.db"


def _load_dotenv() -> None:
    """Load `.env` if python-dotenv is available.

    Real environment variables win, so an explicit ``MAX_ROUNDS=2 uv run consensus``
    still overrides the file. LangGraph Studio loads `.env` itself via
    ``langgraph.json``; this is what gives the CLI and library the same behaviour.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional at runtime
        return
    load_dotenv(override=False)


_load_dotenv()


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(
            f"{name}={raw!r} is not an integer. Expected a whole number "
            f"of at least {minimum} (default: {default})."
        ) from None
    if value < minimum:
        raise ValueError(f"{name}={value} is below the minimum of {minimum}.")
    return value


def _env_str(name: str, default: str, *, allowed: tuple[str, ...]) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value not in allowed:
        raise ValueError(
            f"{name}={raw!r} is not a recognised value. "
            f"Expected one of {', '.join(allowed)} (default: {default})."
        )
    return value


def _check_role(role: str) -> str:
    if role not in ROLE_PREFIXES:
        raise KeyError(f"Unknown role {role!r}. Expected one of {list(ROLE_PREFIXES)}.")
    return ROLE_PREFIXES[role]


def max_rounds() -> int:
    """Author/reviewer rounds to run before giving up. ``MAX_ROUNDS``."""
    return _env_int("MAX_ROUNDS", DEFAULT_MAX_ROUNDS, minimum=1)


def stall_patience() -> int:
    """Consecutive non-improving reviews that end the loop. ``STALL_PATIENCE``."""
    return _env_int("STALL_PATIENCE", DEFAULT_STALL_PATIENCE, minimum=1)


def model_spec(role: str) -> str:
    """The ``provider:model`` spec for a role. ``<ROLE>_MODEL``."""
    prefix = _check_role(role)
    return os.environ.get(f"{prefix}_MODEL") or DEFAULT_MODELS[role]


def max_tokens(role: str) -> int:
    """Output cap for a role. ``<ROLE>_MAX_TOKENS``."""
    prefix = _check_role(role)
    return _env_int(
        f"{prefix}_MAX_TOKENS", DEFAULT_MAX_TOKENS[role], minimum=256
    )


def effort(role: str) -> str:
    """``reasoning_effort`` for a role. ``<ROLE>_EFFORT``."""
    prefix = _check_role(role)
    return _env_str(f"{prefix}_EFFORT", DEFAULT_EFFORT, allowed=VALID_EFFORTS)


def openrouter_ignore_providers() -> list[str]:
    """OpenRouter backends to exclude from routing. ``OPENROUTER_IGNORE_PROVIDERS``.

    Comma-separated provider names as OpenRouter spells them (``Azure``,
    ``Amazon Bedrock``, ...). Setting the variable to an empty string clears the
    default and lets routing reach every backend.
    """
    raw = os.environ.get("OPENROUTER_IGNORE_PROVIDERS")
    if raw is None:
        return list(DEFAULT_OPENROUTER_IGNORE_PROVIDERS)
    return [name.strip() for name in raw.split(",") if name.strip()]


def db_path() -> str:
    """SQLite file the web UI persists run history to. ``CONSENSUS_DB_PATH``.

    Not validated beyond "nonempty" — any string is a valid path, and sqlite
    creates the file itself, so there's nothing to fail loudly about here.
    """
    raw = os.environ.get("CONSENSUS_DB_PATH")
    return raw.strip() if raw and raw.strip() else DEFAULT_DB_PATH


def settings() -> dict[str, object]:
    """Every resolved setting, for logging and transcript headers."""
    return {
        "max_rounds": max_rounds(),
        "stall_patience": stall_patience(),
        "roles": {
            role: {
                "model": model_spec(role),
                "max_tokens": max_tokens(role),
                "effort": effort(role),
            }
            for role in ROLE_PREFIXES
        },
    }
