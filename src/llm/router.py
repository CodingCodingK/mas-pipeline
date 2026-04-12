"""Model name routing: resolve model name or tier to the correct LLM adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.llm.anthropic import AnthropicAdapter
from src.llm.openai_compat import OpenAICompatAdapter
from src.project.config import get_settings

if TYPE_CHECKING:
    from src.llm.adapter import LLMAdapter

_PREFIX_MAP: dict[str, str] = {
    "gpt-": "openai",
    "o1-": "openai",
    "o3-": "openai",
    "o4-": "openai",
    "claude-": "anthropic",
    "gemini-": "gemini",
    "deepseek-": "deepseek",
}

_TIERS = {"strong", "medium", "light"}


def _resolve_tier(name: str) -> str | None:
    """If name is a tier (strong/medium/light), return the configured model name."""
    if name not in _TIERS:
        return None
    settings = get_settings()
    return getattr(settings.models, name)


def _match_provider(model_name: str) -> str:
    """Match model name to provider via prefix map."""
    for prefix, provider in _PREFIX_MAP.items():
        if model_name.startswith(prefix):
            return provider
    raise ValueError(
        f"Cannot route model '{model_name}': no matching provider. "
        f"Known prefixes: {', '.join(_PREFIX_MAP.keys())}"
    )


def validate_model_providers() -> list[str]:
    """Check that every configured tier has a provider with a non-empty API key.

    Returns a list of error messages (empty = all good).
    Called at startup to fail fast instead of 401-ing at runtime.
    """
    settings = get_settings()
    errors: list[str] = []
    for tier in ("strong", "medium", "light"):
        model_name = getattr(settings.models, tier)
        try:
            provider_name = _match_provider(model_name)
        except ValueError as exc:
            errors.append(f"tier '{tier}' (model={model_name}): {exc}")
            continue
        provider_cfg = settings.providers.get(provider_name)
        if provider_cfg is None:
            errors.append(
                f"tier '{tier}' uses model '{model_name}' → provider '{provider_name}' "
                f"not found in settings.providers"
            )
        elif not provider_cfg.api_key or provider_cfg.api_key.startswith("${"):
            errors.append(
                f"tier '{tier}' uses model '{model_name}' → provider '{provider_name}' "
                f"has no API key configured"
            )
    return errors


def route(model_name: str) -> LLMAdapter:
    """Route a model name or tier to an LLMAdapter instance."""
    resolved = _resolve_tier(model_name)
    if resolved is not None:
        model_name = resolved

    provider_name = _match_provider(model_name)

    settings = get_settings()
    provider_cfg = settings.providers.get(provider_name)
    if provider_cfg is None:
        raise ValueError(
            f"Provider '{provider_name}' not configured in settings.providers"
        )

    if provider_name == "anthropic":
        return AnthropicAdapter(
            api_base=provider_cfg.api_base,
            api_key=provider_cfg.api_key,
            model=model_name,
        )

    return OpenAICompatAdapter(
        api_base=provider_cfg.api_base,
        api_key=provider_cfg.api_key,
        model=model_name,
    )
