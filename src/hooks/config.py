"""Hook configuration: loading from settings.yaml and agent frontmatter."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.hooks.types import HookEventType

logger = logging.getLogger(__name__)


@dataclass
class HookConfig:
    """Configuration for a single hook execution."""

    type: str           # "command" or "prompt"
    command: str = ""   # Shell command (for command type)
    prompt: str = ""    # Prompt template (for prompt type)
    timeout: int = 30   # Timeout in seconds


class HookConfigError(Exception):
    """Raised when hook configuration is invalid."""


def validate_hook_config(config: HookConfig) -> None:
    """Validate a hook config, raise HookConfigError if invalid."""
    if config.type not in ("command", "prompt"):
        raise HookConfigError(f"Invalid hook type: '{config.type}'. Must be 'command' or 'prompt'.")
    if config.type == "command" and not config.command:
        raise HookConfigError("Command hook must have a non-empty 'command' field.")
    if config.type == "prompt" and not config.prompt:
        raise HookConfigError("Prompt hook must have a non-empty 'prompt' field.")


def _parse_hook_entry(entry: dict) -> HookConfig:
    """Parse a single hook dict into HookConfig."""
    config = HookConfig(
        type=entry.get("type", ""),
        command=entry.get("command", ""),
        prompt=entry.get("prompt", ""),
        timeout=entry.get("timeout", 30),
    )
    validate_hook_config(config)
    return config


def _parse_event_type(key: str) -> HookEventType:
    """Convert a string key to HookEventType, raise on invalid."""
    try:
        return HookEventType(key)
    except ValueError:
        raise HookConfigError(f"Unknown hook event type: '{key}'") from None


def load_hooks_from_settings(
    settings_hooks: dict,
) -> list[tuple[HookEventType, str | None, HookConfig]]:
    """Parse hooks from the settings.yaml 'hooks' section.

    Expected format:
        hooks:
          pre_tool_use:
            - matcher: "shell"
              hooks:
                - type: command
                  command: "python validate.py"
                  timeout: 10

    Returns list of (event_type, matcher, hook_config) tuples.
    """
    result: list[tuple[HookEventType, str | None, HookConfig]] = []

    if not settings_hooks or not isinstance(settings_hooks, dict):
        return result

    for event_key, matcher_list in settings_hooks.items():
        event_type = _parse_event_type(event_key)

        if not isinstance(matcher_list, list):
            logger.warning("Hooks config for '%s' should be a list, skipping", event_key)
            continue

        for matcher_entry in matcher_list:
            if not isinstance(matcher_entry, dict):
                continue
            matcher = matcher_entry.get("matcher")
            hooks_list = matcher_entry.get("hooks", [])
            if not isinstance(hooks_list, list):
                continue

            for hook_dict in hooks_list:
                try:
                    config = _parse_hook_entry(hook_dict)
                    result.append((event_type, matcher, config))
                except HookConfigError as e:
                    logger.warning("Invalid hook config in settings: %s", e)

    return result


def load_hooks_from_frontmatter(
    frontmatter_hooks: dict,
) -> list[tuple[HookEventType, str | None, HookConfig]]:
    """Parse hooks from agent .md frontmatter 'hooks' field.

    Same format as settings.yaml hooks section.
    """
    return load_hooks_from_settings(frontmatter_hooks)
