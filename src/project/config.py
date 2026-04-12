"""Configuration system with YAML loading + env var substitution + 3-layer merge."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from src.sandbox.types import SandboxConfig

# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"

# Regex for ${VAR} and ${VAR:default}
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _substitute_env(value: str) -> str:
    """Replace ${VAR} and ${VAR:default} with environment variable values."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_val = os.environ.get(var_name)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        return match.group(0)  # keep original if no env and no default

    return _ENV_PATTERN.sub(_replace, value)


def _walk_substitute(obj: Any) -> Any:
    """Recursively substitute env vars in all string values."""
    if isinstance(obj, str):
        return _substitute_env(obj)
    if isinstance(obj, dict):
        return {k: _walk_substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_substitute(item) for item in obj]
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override wins on leaf conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ProviderConfig(BaseModel):
    api_key: str = ""
    api_base: str = ""


class ModelsConfig(BaseModel):
    strong: str = "gpt-5.4"
    medium: str = "gpt-5.4"
    light: str = "gpt-5.4"


class EmbeddingConfig(BaseModel):
    model: str = "text-embedding-3-small"
    provider: str = "openai"
    dimensions: int = 1536


class DatabaseConfig(BaseModel):
    postgres_url: str = "postgresql+asyncpg://mas:mas_dev_2024@localhost:5432/mas_pipeline"
    redis_url: str = "redis://localhost:6379/0"


class AgentConfig(BaseModel):
    max_turns: int = 50
    max_tool_concurrency: int = 10


class CompactConfig(BaseModel):
    autocompact_pct: float = 0.85
    blocking_pct: float = 0.95
    micro_keep_recent: int = 3


class SessionConfig(BaseModel):
    agent_ttl_hours: int = 24
    # Phase 6.1: SessionRunner lifecycle
    idle_timeout_seconds: int = 60
    max_age_seconds: int = 86400


class SpawnAgentConfig(BaseModel):
    # Phase 6.1: hard ceiling for a single sub-agent run.
    timeout_seconds: int = 300


class DefaultUserConfig(BaseModel):
    name: str = "default"
    email: str = ""


class TavilyConfig(BaseModel):
    api_key: str = ""


class ChannelsConfig(BaseModel):
    project_id: int = 1
    role: str = "assistant"
    max_history: int = 50
    session_ttl_hours: int = 24
    discord: dict = {}
    qq: dict = {}
    wechat: dict = {}


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True


class TelemetryConfig(BaseModel):
    enabled: bool = True
    preview_length: int = 30
    batch_size: int = 100
    flush_interval_sec: float = 2.0
    max_queue_size: int = 10000
    pricing_table_path: str = "config/pricing.yaml"


class NotifySettings(BaseModel):
    enabled: bool = True
    wechat_webhook_url: str | None = None
    discord_webhook_url: str | None = None
    sse_queue_size: int = 500
    sse_heartbeat_sec: int = 15
    notify_queue_size: int = 5000


class Settings(BaseModel):
    default_user: DefaultUserConfig = DefaultUserConfig()
    models: ModelsConfig = ModelsConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    providers: dict[str, ProviderConfig] = {}
    database: DatabaseConfig = DatabaseConfig()
    agent: AgentConfig = AgentConfig()
    compact: CompactConfig = CompactConfig()
    session: SessionConfig = SessionConfig()
    spawn_agent: SpawnAgentConfig = SpawnAgentConfig()
    tavily: TavilyConfig = TavilyConfig()
    server: ServerConfig = ServerConfig()
    context_windows: dict[str, int] = {}
    hooks: dict = {}
    permissions: dict = {}
    mcp_servers: dict = {}
    mcp_default_access: str = "all"
    channels: ChannelsConfig = ChannelsConfig()
    sandbox: SandboxConfig = SandboxConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    notify: NotifySettings = NotifySettings()
    # Phase 6.1: REST API auth — empty list disables auth (development mode)
    api_keys: list[str] = []


def load_yaml(path: Path) -> dict:
    """Load a YAML file, return empty dict if not found."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_settings(
    global_path: Path | None = None,
    local_path: Path | None = None,
    pipeline_config: dict | None = None,
    project_config: dict | None = None,
) -> Settings:
    """Load and merge settings: global -> local -> pipeline -> project -> env vars.

    Three-layer merge:
    1. global settings.yaml (defaults)
    2. local settings.local.yaml (user overrides, gitignored)
    3. pipeline-level config (from pipeline YAML)
    4. project-level config (from project DB record)
    5. Environment variable substitution (final pass)
    """
    global_path = global_path or CONFIG_DIR / "settings.yaml"
    local_path = local_path or CONFIG_DIR / "settings.local.yaml"

    # Layer 1: global defaults
    merged = load_yaml(global_path)

    # Layer 2: local overrides
    local = load_yaml(local_path)
    if local:
        merged = _deep_merge(merged, local)

    # Layer 3: pipeline config
    if pipeline_config:
        merged = _deep_merge(merged, pipeline_config)

    # Layer 4: project config
    if project_config:
        merged = _deep_merge(merged, project_config)

    # Layer 5: env var substitution
    merged = _walk_substitute(merged)

    return Settings.model_validate(merged)


# Singleton — lazily initialized
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from disk."""
    global _settings
    _settings = load_settings()
    return _settings
