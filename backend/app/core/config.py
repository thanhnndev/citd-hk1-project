"""Centralized application configuration via pydantic-settings.

All settings load from .env file with fail-fast validation — a missing
required variable raises ValidationError and crashes the app at startup.
"""

from functools import cached_property
from typing import Annotated, List

from pydantic import BeforeValidator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # ── PostgreSQL ──────────────────────────────────────────────
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "ham_ninh"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432

    # ── OpenAI ──────────────────────────────────────────────────
    OPENAI_API_KEY: str
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"

    # ── Goong APIs ──────────────────────────────────────────────
    # Optional: blank values let Places/Routes services fail honestly at runtime.
    GOONG_API_KEY: str = ""

    # ── Langfuse ────────────────────────────────────────────────
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://langfuse:3000"

    # ── CORS ────────────────────────────────────────────────────
    CORS_ORIGINS: Annotated[List[str], BeforeValidator(
        lambda v: [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else v
    )] = ["http://localhost:3000"]

    # ── Authentication ──────────────────────────────────────────
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    REQUIRE_EMAIL_VERIFICATION: bool = False

    # ── SMTP (Email Verification) ──────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Ham Ninh AI"
    SMTP_USE_SSL: bool = True

    # ── Rate Limiting ───────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "60/minute"
    RATE_LIMIT_CHAT: str = "20/minute"

    # ── Server ──────────────────────────────────────────────────
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── DSN helpers ─────────────────────────────────────────────

    @cached_property
    def postgres_dsn(self) -> str:
        """Build PostgreSQL async DSN."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @cached_property
    def redis_url(self) -> str:
        """Build Redis URL."""
        return "redis://redis:6379/0"

    @cached_property
    def qdrant_url(self) -> str:
        """Build Qdrant URL."""
        return "http://qdrant:6333"


# Module-level lazy singleton — created on first access via get_settings().
# Not instantiated at import time so the module is importable during tests.
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a validated Settings singleton.

    Created lazily on first call. Raises RuntimeError if any required
    env var is missing (fail-fast behavior for lifespan startup).
    """
    global _settings
    if _settings is None:
        try:
            _settings = Settings()
        except ValidationError as exc:
            raise RuntimeError(f"Configuration validation failed: {exc}") from exc
    return _settings
