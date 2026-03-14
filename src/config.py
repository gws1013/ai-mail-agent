"""
Application configuration loaded from environment variables / .env file.

Uses pydantic-settings for validation and type coercion.
Access settings via the get_settings() singleton helper.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised application settings.

    All values can be overridden by environment variables or a ``.env`` file
    placed in the project root.  Variable names are case-insensitive.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # AI / LLM
    # ------------------------------------------------------------------ #
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for the Anthropic Claude API (optional).",
    )
    OPENAI_API_KEY: str = Field(
        ...,
        description="API key for the OpenAI API (required).",
    )

    # ------------------------------------------------------------------ #
    # Gmail OAuth
    # ------------------------------------------------------------------ #
    GMAIL_CREDENTIALS_PATH: str = Field(
        default="./credentials/credentials.json",
        description="Path to the Gmail OAuth2 client-secrets JSON file.",
    )
    GMAIL_TOKEN_PATH: str = Field(
        default="./credentials/token.json",
        description="Path where the OAuth2 access/refresh token is persisted.",
    )
    GMAIL_WATCH_LABEL: str = Field(
        default="INBOX",
        description="Gmail label to monitor for incoming messages.",
    )

    # ------------------------------------------------------------------ #
    # Vector store (ChromaDB)
    # ------------------------------------------------------------------ #
    CHROMA_PERSIST_DIR: str = Field(
        default="./chroma_db",
        description="Directory used by ChromaDB for persistent storage.",
    )

    # ------------------------------------------------------------------ #
    # Agent behaviour
    # ------------------------------------------------------------------ #
    AUTO_SEND_THRESHOLD: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence threshold above which the agent sends a reply "
            "automatically without human review."
        ),
    )
    POLL_INTERVAL_SECONDS: int = Field(
        default=300,
        gt=0,
        description="How often (in seconds) to poll the Gmail inbox.",
    )
    MAX_RETRY_COUNT: int = Field(
        default=2,
        ge=0,
        description="Maximum number of times a failed graph node is retried.",
    )

    # ------------------------------------------------------------------ #
    # Cost guardrails
    # ------------------------------------------------------------------ #
    MAX_MONTHLY_COST_USD: float = Field(
        default=50.0,
        gt=0.0,
        description="Hard cap on LLM spend per calendar month (USD).",
    )
    COST_LOG_PATH: str = Field(
        default="./logs/cost.json",
        description="File path where cumulative token/cost usage is logged.",
    )

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Python logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )
    LOG_DIR: str = Field(
        default="./logs",
        description="Directory where rotating log files are written.",
    )

    # ------------------------------------------------------------------ #
    # Optional integrations
    # ------------------------------------------------------------------ #
    SLACK_WEBHOOK_URL: Optional[str] = Field(
        default=None,
        description=(
            "Incoming Webhook URL for Slack notifications.  "
            "Leave unset to disable Slack alerts."
        ),
    )

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalised = v.upper()
        if normalised not in allowed:
            raise ValueError(
                f"LOG_LEVEL must be one of {sorted(allowed)}, got {v!r}."
            )
        return normalised


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application-wide :class:`Settings` singleton.

    The instance is constructed once and cached for the lifetime of the
    process.  In tests, call ``get_settings.cache_clear()`` before patching
    environment variables to force re-initialisation.

    Returns
    -------
    Settings
        The validated, fully-populated settings object.
    """
    return Settings()
