"""Configuration system for ToolWitness.

Precedence: environment variables (TOOLWITNESS_*) > YAML (toolwitness.yaml) > code defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_YAML_AVAILABLE = False
try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    pass


@dataclass
class ToolWitnessConfig:
    """Runtime configuration for ToolWitness."""

    db_path: str = str(Path.home() / ".toolwitness" / "toolwitness.db")
    log_level: str = "WARNING"
    confidence_threshold: float = 0.7
    embellishment_alert: bool = False
    webhook_url: str | None = None
    slack_webhook_url: str | None = None
    alerting_config: dict[str, Any] | None = None

    semantic_enabled: bool = False
    semantic_provider: str = "openai"
    semantic_model: str = "gpt-4o-mini"
    semantic_api_key: str | None = None

    @classmethod
    def load(cls, yaml_path: str | Path | None = None) -> ToolWitnessConfig:
        """Load config with precedence: env > YAML > defaults."""
        config = cls()

        yaml_data = _load_yaml(yaml_path)
        if yaml_data:
            config = _apply_yaml(config, yaml_data)

        config = _apply_env(config)
        return config


def _load_yaml(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML config file if it exists."""
    if not _YAML_AVAILABLE:
        return {}

    candidates = []
    if path:
        candidates.append(Path(path))
    candidates.extend([
        Path("toolwitness.yaml"),
        Path("toolwitness.yml"),
        Path.home() / ".toolwitness" / "toolwitness.yaml",
    ])

    for candidate in candidates:
        if candidate.is_file():
            with open(candidate) as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}

    return {}


def _apply_yaml(config: ToolWitnessConfig, data: dict[str, Any]) -> ToolWitnessConfig:
    """Apply YAML config values."""
    storage = data.get("storage", {})
    if "db_path" in storage:
        config.db_path = str(storage["db_path"])

    if "log_level" in data:
        config.log_level = str(data["log_level"]).upper()

    verification = data.get("verification", {})
    if "confidence_threshold" in verification:
        config.confidence_threshold = float(verification["confidence_threshold"])
    if "embellishment_alert" in verification:
        config.embellishment_alert = bool(verification["embellishment_alert"])

    semantic = verification.get("semantic", {})
    if "enabled" in semantic:
        config.semantic_enabled = bool(semantic["enabled"])
    if "provider" in semantic:
        config.semantic_provider = str(semantic["provider"])
    if "model" in semantic:
        config.semantic_model = str(semantic["model"])
    if "api_key" in semantic:
        config.semantic_api_key = str(semantic["api_key"])

    alerting = data.get("alerting", {})
    if "webhook_url" in alerting:
        config.webhook_url = alerting["webhook_url"]
    if "slack_webhook_url" in alerting:
        config.slack_webhook_url = alerting["slack_webhook_url"]
    if alerting:
        config.alerting_config = alerting

    return config


def _apply_env(config: ToolWitnessConfig) -> ToolWitnessConfig:
    """Apply environment variable overrides (highest precedence)."""
    env_map = {
        "TOOLWITNESS_DB_PATH": "db_path",
        "TOOLWITNESS_LOG_LEVEL": "log_level",
        "TOOLWITNESS_CONFIDENCE_THRESHOLD": "confidence_threshold",
        "TOOLWITNESS_EMBELLISHMENT_ALERT": "embellishment_alert",
        "TOOLWITNESS_WEBHOOK_URL": "webhook_url",
        "TOOLWITNESS_SLACK_WEBHOOK_URL": "slack_webhook_url",
        "TOOLWITNESS_SEMANTIC_PROVIDER": "semantic_provider",
        "TOOLWITNESS_SEMANTIC_MODEL": "semantic_model",
        "TOOLWITNESS_SEMANTIC_API_KEY": "semantic_api_key",
    }

    api_key = os.environ.get("TOOLWITNESS_SEMANTIC_API_KEY")
    if api_key and not os.environ.get("TOOLWITNESS_SEMANTIC_ENABLED"):
        config.semantic_enabled = True
        config.semantic_api_key = api_key

    semantic_enabled_env = os.environ.get("TOOLWITNESS_SEMANTIC_ENABLED")
    if semantic_enabled_env is not None:
        config.semantic_enabled = semantic_enabled_env.lower() in ("true", "1", "yes")

    for env_key, attr in env_map.items():
        value = os.environ.get(env_key)
        if value is None:
            continue

        current = getattr(config, attr)
        if isinstance(current, bool):
            setattr(config, attr, value.lower() in ("true", "1", "yes"))
        elif isinstance(current, float):
            setattr(config, attr, float(value))
        elif isinstance(current, int):
            setattr(config, attr, int(value))
        else:
            setattr(config, attr, value)

    return config
