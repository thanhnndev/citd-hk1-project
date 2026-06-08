"""Pytest configuration for backend tests.

Sets required environment variables before any app modules are imported.
This prevents Settings validation errors when importing app.routers.chat
which calls get_settings() at module level.
"""

import os
import pytest

# Direct assignment — guaranteed to set the value regardless of prior state
os.environ["OPENAI_API_KEY"] = "test-key-for-unit-tests"
os.environ["APP_ENV"] = "test"


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch):
    """Ensure required env vars are set before every test.

    Uses monkeypatch so values are automatically restored after each test.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-for-unit-tests")
    monkeypatch.setenv("APP_ENV", "test")
