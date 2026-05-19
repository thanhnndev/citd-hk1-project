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
