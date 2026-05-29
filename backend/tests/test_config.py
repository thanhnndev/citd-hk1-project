"""Tests for application settings validation and optional Goong credentials."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_instantiates_without_goong_api_key(monkeypatch):
    """Goong key is optional so Places/Routes services can report blocked status."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("GOONG_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.OPENAI_API_KEY == "test-openai-key"
    assert settings.GOONG_API_KEY == ""


def test_settings_preserves_empty_goong_api_key(monkeypatch):
    """Explicit blank Goong credential remains blank instead of failing startup."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GOONG_API_KEY", "")

    settings = Settings(_env_file=None)

    assert settings.GOONG_API_KEY == ""


def test_settings_still_requires_openai_api_key(monkeypatch):
    """Required app secrets retain fail-fast Pydantic validation."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOONG_API_KEY", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error_text = str(exc_info.value)
    assert "OPENAI_API_KEY" in error_text
    assert "GOONG_API_KEY" not in error_text
