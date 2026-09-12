"""Configuration loader. Reads config.yaml, merges with defaults."""

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path(__file__).parent.parent / "config.example.yaml"
USER_CONFIG = Path.home() / ".omnicore" / "config.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from path, falling back to env vars and defaults."""
    config = {}

    # 1. Load defaults
    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG) as f:
            config = yaml.safe_load(f) or {}

    # 2. Load user config (overrides defaults)
    target = path or USER_CONFIG
    if target.exists():
        with open(target) as f:
            user = yaml.safe_load(f) or {}
            _deep_merge(config, user)

    # 3. Env var overrides (highest priority)
    _apply_env_overrides(config)

    return config


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base recursively."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _apply_env_overrides(config: dict) -> None:
    """Apply environment variable overrides."""
    providers = config.get("provider", {})
    for name in ("openai", "anthropic", "gemini", "deepseek", "openrouter"):
        env_key = f"OMNICORE_{name.upper()}_KEY"
        if env_key in os.environ:
            providers.setdefault(name, {})["api_key"] = os.environ[env_key]


def get_provider_config(config: dict, name: str) -> dict:
    """Extract provider-specific config with defaults."""
    return config.get("provider", {}).get(name, {})


def get_tool_config(config: dict) -> dict:
    """Extract tool configuration."""
    return config.get("tools", {})


def get_agent_config(config: dict) -> dict:
    """Extract agent configuration."""
    return config.get("agent", {})