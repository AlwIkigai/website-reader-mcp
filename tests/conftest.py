import os

import pytest

from app.config import Settings

os.environ.setdefault("MCP_API_KEY", "test-key")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("CACHE_ENABLED", "false")


@pytest.fixture
def settings_without_env(monkeypatch):
    """Build Settings from explicit values, ignoring MCP_ALLOWED_HOSTS from the environment."""
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)

    def _build(**overrides) -> Settings:
        payload = {"mcp_api_key": "test-key", **overrides}
        return Settings(**payload)

    return _build
