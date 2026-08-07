"""Persistent, manually refreshed OpenRouter model choices for the web UI."""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Any

from . import config, db
from .models import parse_spec

CATALOG_URL = (
    "https://openrouter.ai/api/v1/models?output_modalities=text&sort=most-popular"
)
DEFAULT_CATALOG_LIMIT = 30
MAX_CATALOG_LIMIT = 100


def openrouter_id(spec: str) -> str:
    """Convert any supported provider spec to its OpenRouter namespaced ID."""
    provider, model = parse_spec(spec)
    if provider == "openrouter":
        return model
    return f"{provider}/{model}"


def default_model_ids() -> dict[str, str]:
    return {role: openrouter_id(config.model_spec(role)) for role in config.ROLE_PREFIXES}


def _configured_model(model_id: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": model_id,
        "provider": model_id.split("/", 1)[0],
        "prompt_price": None,
        "completion_price": None,
        "context_length": None,
        "supported_parameters": [],
        "popularity_rank": None,
        "refreshed_at": None,
        "configured_default": True,
    }


def available_models(*, path: str | None = None) -> dict[str, Any]:
    saved = db.get_model_catalog(path=path)
    models = list(saved["models"])
    present = {item["id"] for item in models}
    defaults = default_model_ids()
    for model_id in dict.fromkeys(defaults.values()):
        if model_id not in present:
            models.append(_configured_model(model_id))
    return {
        "models": models,
        "defaults": defaults,
        "refreshed_at": saved["refreshed_at"],
        "saved_count": len(saved["models"]),
    }


def validate_model_id(model_id: str, *, path: str | None = None) -> str:
    value = model_id.strip()
    allowed = {item["id"] for item in available_models(path=path)["models"]}
    if value not in allowed:
        raise ValueError(f"model {value!r} is not in the saved OpenRouter catalog")
    return value


def settings_with_models(
    selected: dict[str, str] | None, *, base: dict[str, Any] | None = None,
    roles: tuple[str, ...] = ("moderator", "agent_a", "agent_b"),
) -> dict[str, Any]:
    """Return a credential-free settings snapshot with validated web overrides."""
    snapshot = base or config.settings()
    selected = selected or {}
    unknown = set(selected) - set(roles)
    if unknown:
        raise ValueError(f"unknown model role(s): {', '.join(sorted(unknown))}")
    for role in roles:
        model_id = selected.get(role)
        if model_id:
            snapshot["roles"][role]["model"] = (
                f"openrouter:{validate_model_id(model_id)}"
            )
    return snapshot


def fetch_popular_models(
    *, limit: int = DEFAULT_CATALOG_LIMIT, timeout: float = 10.0
) -> list[dict[str, Any]]:
    """Fetch and normalize the most popular usable text models from OpenRouter."""
    if not 1 <= limit <= MAX_CATALOG_LIMIT:
        raise ValueError(
            f"model count must be between 1 and {MAX_CATALOG_LIMIT}"
        )
    from . import runtime_settings

    headers = {"Accept": "application/json", "User-Agent": "agentic-consensus/0.1"}
    api_key = runtime_settings.value("OPENROUTER_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(CATALOG_URL, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("OpenRouter returned an invalid model catalog")
    today = date.today().isoformat()
    result = []
    for raw in data:
        architecture = raw.get("architecture") or {}
        outputs = architecture.get("output_modalities") or []
        expires = raw.get("expiration_date")
        model_id = raw.get("id")
        if not model_id or "text" not in outputs or (expires and expires <= today):
            continue
        pricing = raw.get("pricing") or {}
        result.append({
            "id": model_id,
            "name": raw.get("name") or model_id,
            "provider": model_id.split("/", 1)[0],
            "prompt_price": pricing.get("prompt"),
            "completion_price": pricing.get("completion"),
            "context_length": raw.get("context_length"),
            "supported_parameters": raw.get("supported_parameters") or [],
            "popularity_rank": len(result) + 1,
        })
        if len(result) == limit:
            break
    if not result:
        raise ValueError("OpenRouter returned no usable text models")
    return result


def refresh(
    *, limit: int = DEFAULT_CATALOG_LIMIT, path: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    models = fetch_popular_models(limit=limit, timeout=timeout)
    db.replace_model_catalog(models, path=path)
    return available_models(path=path)
