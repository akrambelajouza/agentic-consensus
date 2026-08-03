"""Provider-neutral token accounting plus provider-reported billing metadata."""

from . import config
from .models import parse_spec
from .schemas import Usage


def usage_from_message(node: str, role: str, message) -> Usage:
    """Merge LangChain's normalized tokens with raw provider cost metadata."""
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


__all__ = ["usage_from_message"]
