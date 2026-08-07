"""Persisted web settings layered over environment configuration."""

from __future__ import annotations

import os
from typing import Any

from . import db

SETTING_NAMES = (
    "OPENROUTER_API_KEY",
    "LANGSMITH_API_KEY",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_TRACING",
    "LANGSMITH_PROJECT",
)
SECRET_NAMES = {"OPENROUTER_API_KEY", "LANGSMITH_API_KEY"}
LANGSMITH_NAMES = tuple(name for name in SETTING_NAMES if name.startswith("LANGSMITH_"))

# dotenv has already been loaded by config before this module is imported by web or
# models. Retain those values so clearing an SQLite override restores the fallback.
_ENV_DEFAULTS = {name: os.environ.get(name) for name in SETTING_NAMES}


def value(name: str, *, path: str | None = None) -> str | None:
    if name not in SETTING_NAMES:
        raise KeyError(f"unsupported application setting {name!r}")
    saved = db.get_app_settings(path=path).get(name)
    return saved if saved is not None else _ENV_DEFAULTS.get(name)


def public_settings(*, path: str | None = None) -> dict[str, Any]:
    saved = db.get_app_settings(path=path)
    result: dict[str, Any] = {}
    for name in SETTING_NAMES:
        effective = saved.get(name, _ENV_DEFAULTS.get(name))
        item: dict[str, Any] = {
            "configured": bool(effective),
            "source": "sqlite" if name in saved else "environment",
        }
        if name not in SECRET_NAMES:
            item["value"] = saved.get(name, "")
            item["effective_value"] = effective or ""
        result[name] = item
    return result


def save(values: dict[str, str | None], *, path: str | None = None) -> None:
    unknown = set(values) - set(SETTING_NAMES)
    if unknown:
        raise ValueError(f"unsupported setting(s): {', '.join(sorted(unknown))}")
    tracing = values.get("LANGSMITH_TRACING")
    if tracing and tracing.strip().lower() not in {"true", "false"}:
        raise ValueError("LANGSMITH_TRACING must be true or false")
    normalized = dict(values)
    if tracing:
        normalized["LANGSMITH_TRACING"] = tracing.strip().lower()
    db.replace_app_settings(normalized, path=path)
    apply_langsmith_environment(path=path)


def apply_langsmith_environment(*, path: str | None = None) -> None:
    """Apply effective LangSmith settings for SDKs that read process environment."""
    saved = db.get_app_settings(path=path)
    for name in LANGSMITH_NAMES:
        effective = saved.get(name, _ENV_DEFAULTS.get(name))
        if effective:
            os.environ[name] = effective
        else:
            os.environ.pop(name, None)
