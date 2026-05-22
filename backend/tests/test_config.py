"""Tests for application settings validation and optional upstream credentials."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_instantiates_without_google_api_keys(monkeypatch):
    """Google Places/Routes keys are optional so services can report blocked status."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.OPENAI_API_KEY == "test-openai-key"
    assert settings.embedding_api_key == "test-openai-key"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.GOOGLE_PLACES_API_KEY == ""
    assert settings.GOOGLE_ROUTES_API_KEY == ""


def test_settings_preserves_empty_google_api_keys(monkeypatch):
    """Explicit blank Google credentials remain blank instead of failing startup."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "")
    monkeypatch.setenv("GOOGLE_ROUTES_API_KEY", "")

    settings = Settings(_env_file=None)

    assert settings.GOOGLE_PLACES_API_KEY == ""
    assert settings.GOOGLE_ROUTES_API_KEY == ""


def test_settings_still_requires_openai_api_key(monkeypatch):
    """Required app secrets retain fail-fast Pydantic validation."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_ROUTES_API_KEY", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error_text = str(exc_info.value)
    assert "OPENAI_API_KEY" in error_text
    assert "GOOGLE_PLACES_API_KEY" not in error_text
    assert "GOOGLE_ROUTES_API_KEY" not in error_text


def test_settings_supports_separate_embedding_provider(monkeypatch):
    """Embedding credentials and provider endpoint can differ from the LLM."""
    monkeypatch.setenv("OPENAI_API_KEY", "llm-key")
    monkeypatch.setenv("EMBEDDING_API_KEY", "qwen-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://dashscope.example/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "10")

    settings = Settings(_env_file=None)

    assert settings.embedding_api_key == "qwen-key"
    assert settings.EMBEDDING_BASE_URL == "https://dashscope.example/v1"
    assert settings.embedding_model == "text-embedding-v4"
    assert settings.EMBEDDING_DIMENSIONS == 1536
    assert settings.EMBEDDING_BATCH_SIZE == 10
