"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised application settings.

    All values can be overridden by environment variables or a ``.env`` file
    placed in the project root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── AI / LLM ─────────────────────────────────────────────────
    OPENAI_API_KEY: str = Field(
        ...,
        description="OpenAI API key.",
    )

    # ── Gmail OAuth ──────────────────────────────────────────────
    GMAIL_CREDENTIALS_PATH: str = Field(
        default="./credentials/credentials.json",
        description="Path to Gmail OAuth2 credentials.json.",
    )
    GMAIL_TOKEN_PATH: str = Field(
        default="./credentials/token.json",
        description="Path to persisted OAuth2 token.",
    )
    GMAIL_WATCH_LABEL: str = Field(
        default="INBOX",
        description="Gmail label to monitor.",
    )

    # ── Vector store ─────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = Field(
        default="./chroma_db",
        description="ChromaDB persistent storage directory.",
    )

    # ── Agent behaviour ──────────────────────────────────────────
    POLL_INTERVAL_SECONDS: int = Field(
        default=10,
        gt=0,
        description="How often (seconds) to poll Gmail inbox.",
    )
    MAX_RETRY_COUNT: int = Field(
        default=2,
        ge=0,
        description="Max retries for failed graph nodes.",
    )

    # ── Cost guardrails ──────────────────────────────────────────
    MAX_MONTHLY_COST_USD: float = Field(
        default=50.0,
        gt=0.0,
        description="Hard cap on LLM spend per month (USD).",
    )
    COST_LOG_PATH: str = Field(
        default="./logs/cost.json",
        description="File path for cumulative cost log.",
    )

    # ── Logging ──────────────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO")
    LOG_DIR: str = Field(default="./logs")

    # ── Validators ───────────────────────────────────────────────
    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalised = v.upper()
        if normalised not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got {v!r}.")
        return normalised


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application-wide Settings singleton."""
    return Settings()
