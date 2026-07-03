import pytest
from starlette.requests import Request

from app.auth import is_allowed_mcp_client, is_valid_api_key
from app.config import Settings


def _request(
    *,
    host: str | None = "example.com",
    origin: str | None = None,
    api_key: str | None = "test-key",
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if host is not None:
        headers.append((b"host", host.encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if api_key is not None:
        headers.append((b"authorization", f"Bearer {api_key}".encode()))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/mcp/",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("example.com", 443),
        "scheme": "https",
    }
    return Request(scope)


def test_mcp_client_allowed_when_host_allowlist_disabled(settings_without_env):
    settings = settings_without_env()

    assert is_allowed_mcp_client(_request(host="anything.test"), settings) is True


def test_mcp_client_rejected_for_unlisted_host(settings_without_env):
    settings = settings_without_env(mcp_allowed_hosts="allowed.example")

    assert is_allowed_mcp_client(_request(host="blocked.example"), settings) is False
    assert is_allowed_mcp_client(_request(host="allowed.example"), settings) is True


def test_mcp_client_allowed_for_subdomain_wildcard(settings_without_env):
    settings = settings_without_env(mcp_allowed_hosts="*.example.com")

    assert is_allowed_mcp_client(_request(host="api.example.com"), settings) is True
    assert is_allowed_mcp_client(_request(host="example.com"), settings) is False


def test_mcp_client_rejects_origin_not_on_allowlist(settings_without_env):
    settings = settings_without_env(
        mcp_allowed_hosts="*",
        mcp_allowed_origins="https://trusted.example",
    )

    assert is_allowed_mcp_client(_request(origin="https://trusted.example"), settings) is True
    assert is_allowed_mcp_client(_request(origin="https://evil.example"), settings) is False
    assert is_allowed_mcp_client(_request(origin=None), settings) is True


def test_api_key_validation(settings_without_env):
    settings = settings_without_env()

    assert is_valid_api_key(_request(api_key="test-key"), settings) is True
    assert is_valid_api_key(_request(api_key="wrong"), settings) is False
