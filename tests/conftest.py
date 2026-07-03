import os

import pytest

from app.config import Settings

os.environ.setdefault("MCP_API_KEY", "test-key")
os.environ.setdefault("APP_ENV", "test")


@pytest.fixture
def settings_without_env(monkeypatch):
    """Build Settings from explicit values, ignoring ALLOWED_DOMAINS from the environment."""
    monkeypatch.delenv("ALLOWED_DOMAINS", raising=False)

    def _build(**overrides) -> Settings:
        payload = {"mcp_api_key": "test-key", **overrides}
        return Settings(**payload)

    return _build
