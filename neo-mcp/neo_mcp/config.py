"""Configuration for the neo-mcp self-healing agent platform.

Uses dataclass-based config with .env file loading via python-dotenv.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from dotenv import load_dotenv


@dataclass
class LLMProviderConfig:
    """Configuration for an LLM provider."""

    api_key: str = ""
    """API key for the LLM provider."""

    model_id: str = ""
    """Model identifier string (e.g., 'claude-opus-4-8')."""

    max_retries: int = 3
    """Maximum number of retries for API calls."""

    timeout_seconds: int = 60
    """Timeout in seconds for API calls."""


@dataclass
class RecoveryConfig:
    """Configuration for the recovery subsystem."""

    max_attempts: int = 3
    """Maximum recovery attempts per step."""

    base_backoff_delay: float = 1.0
    """Base delay in seconds for exponential backoff."""

    max_backoff_delay: float = 30.0
    """Maximum delay in seconds for exponential backoff."""


@dataclass
class AgentConfig:
    """Top-level configuration for the neo-mcp agent platform."""

    # LLM Provider configs
    planner_llm: LLMProviderConfig = field(
        default_factory=lambda: LLMProviderConfig(
            model_id=os.environ.get("PLANNER_MODEL_ID", "claude-opus-4-8"),
        )
    )
    """Configuration for the planner's LLM provider."""

    argument_repairer_llm: LLMProviderConfig = field(
        default_factory=lambda: LLMProviderConfig(
            model_id=os.environ.get("ARGUMENT_REPAIRER_MODEL_ID", "claude-opus-4-8"),
        )
    )
    """Configuration for the argument repairer's LLM provider."""

    failure_classifier_llm: LLMProviderConfig = field(
        default_factory=lambda: LLMProviderConfig(
            model_id=os.environ.get(
                "FAILURE_CLASSIFIER_MODEL_ID",
                "claude-haiku-4-5-20251001",
            ),
        )
    )
    """Configuration for the failure classifier's LLM provider."""

    # Recovery config
    recovery: RecoveryConfig = field(default_factory=RecoveryConfig)
    """Recovery subsystem configuration."""

    # API keys (loaded from environment / .env)
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    """Anthropic API key. Set via ANTHROPIC_API_KEY env var or .env file."""

    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    """OpenAI API key. Set via OPENAI_API_KEY env var or .env file."""

    openrouter_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", "")
    )
    """OpenRouter API key. Set via OPENROUTER_API_KEY env var or .env file."""

    verbose_instrumentation: bool = True
    """Whether instrumentation should print verbose output."""


def load_config(env_file: Optional[str] = None) -> AgentConfig:
    """Load configuration from environment variables and optional .env file.

    Args:
        env_file: Optional path to a .env file. If None, uses default
            locations (current dir, parent dirs).

    Returns:
        An AgentConfig instance populated from environment variables.
    """
    load_dotenv(dotenv_path=env_file)

    config = AgentConfig()

    # Override API keys (already loaded via field defaults, but re-read explicitly)
    config.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    config.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    config.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")

    # Override LLM provider API keys if set
    for llm_config in [config.planner_llm, config.argument_repairer_llm, config.failure_classifier_llm]:
        llm_config.api_key = config.anthropic_api_key

    # Override recovery config from env
    if os.environ.get("MAX_RECOVERY_ATTEMPTS"):
        config.recovery.max_attempts = int(os.environ["MAX_RECOVERY_ATTEMPTS"])
    if os.environ.get("BASE_BACKOFF_DELAY"):
        config.recovery.base_backoff_delay = float(os.environ["BASE_BACKOFF_DELAY"])
    if os.environ.get("MAX_BACKOFF_DELAY"):
        config.recovery.max_backoff_delay = float(os.environ["MAX_BACKOFF_DELAY"])

    # Instrumentation verbosity
    verbose = os.environ.get("VERBOSE_INSTRUMENTATION", "true").lower()
    config.verbose_instrumentation = verbose in ("true", "1", "yes")

    return config