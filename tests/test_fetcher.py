import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.cache import reset_url_cache
from app.ratelimit import reset_rate_limiter
from app.ratelimit.client_id import build_client_id
from app.ratelimit.context import client_id_ctx
from app.services.fetch_types import FetchResponse
from app.services.fetcher import FetchError, URLValidationError, fetch_url_content, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "https://LOCALHOST/test",
        "http://127.0.0.1/",
        "https://127.0.0.2/secret",
        "http://127.0.0.1:8000",
        "http://192.168.0.1/",
        "https://192.168.1.10/page",
        "http://10.0.0.5/page",
        "https://10.255.255.255/",
        "http://172.31.255.255/",
        "https://172.16.0.1/page",
        "https://[::1]/",
        "http://[::1]/page",
        "http://169.254.1.1/",
        "https://169.254.169.254/latest/meta-data",
        "ftp://example.com/file",
        "not-a-url",
        "",
    ],
)
def test_validate_url_rejects_unsafe_or_invalid_urls(url: str):
    with pytest.raises(URLValidationError):
        validate_url(url)


def test_validate_url_accepts_public_http_and_https():
    http = validate_url("http://example.com")
    https = validate_url("https://example.org/path")

    assert http.scheme == "http"
    assert https.scheme == "https"
    assert https.hostname == "example.org"


def _mock_httpx_response(body: bytes = b"<html><body>Hello</body></html>") -> MagicMock:
    response = MagicMock()
    response.url = "https://example.com/page"
    response.status_code = 200
    response.encoding = "utf-8"
    response.headers = {"content-type": "text/html; charset=utf-8"}

    async def _aiter_bytes():
        yield body

    response.aiter_bytes = _aiter_bytes
    return response


def _mock_httpx_client(response: MagicMock) -> MagicMock:
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=response)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.stream = MagicMock(return_value=stream_cm)

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=client)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    return client_cm


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_url_cache()
    reset_rate_limiter()
    yield
    reset_url_cache()
    reset_rate_limiter()


@pytest.mark.asyncio
async def test_fetch_url_content_uses_cache_on_second_request(settings_without_env):
    settings = settings_without_env(
        cache_enabled=True,
        cache_backend="memory",
        cache_ttl_seconds=60,
        cache_max_entries=10,
    )
    response = _mock_httpx_response()
    client_cm = _mock_httpx_client(response)

    with patch("app.services.fetcher.httpx.AsyncClient", return_value=client_cm):
        first = await fetch_url_content("https://example.com/page", settings)
        second = await fetch_url_content("https://example.com/page", settings)

    assert first == second
    assert first.body == "<html><body>Hello</body></html>"
    assert client_cm.__aenter__.await_count == 1


@pytest.mark.asyncio
async def test_fetch_url_content_skips_cache_when_disabled(settings_without_env):
    settings = settings_without_env(cache_enabled=False)
    response = _mock_httpx_response()
    client_cm = _mock_httpx_client(response)

    with patch("app.services.fetcher.httpx.AsyncClient", return_value=client_cm):
        await fetch_url_content("https://example.com/page", settings)
        await fetch_url_content("https://example.com/page", settings)

    assert client_cm.__aenter__.await_count == 2


@pytest.mark.asyncio
async def test_fetch_url_content_does_not_cache_errors(settings_without_env):
    settings = settings_without_env(
        cache_enabled=True,
        cache_backend="memory",
        cache_ttl_seconds=60,
        cache_max_entries=10,
    )
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(side_effect=FetchError("network down"))
    client_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.fetcher.httpx.AsyncClient", return_value=client_cm):
        with pytest.raises(FetchError, match="network down"):
            await fetch_url_content("https://example.com/page", settings)

        with pytest.raises(FetchError, match="network down"):
            await fetch_url_content("https://example.com/page", settings)

    assert client_cm.__aenter__.await_count == 2


@pytest.mark.asyncio
async def test_memory_cache_round_trip():
    from app.cache.memory import MemoryUrlCache

    cache = MemoryUrlCache(ttl_seconds=60, max_entries=10)
    entry = FetchResponse(
        url="https://example.com",
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html",
        body="<p>cached</p>",
    )

    await cache.set("https://example.com", entry)
    cached = await cache.get("https://example.com")

    assert cached == entry


@pytest.mark.asyncio
async def test_fetch_url_content_enforces_rate_limit(settings_without_env):
    settings = settings_without_env(
        rate_limit_enabled=True,
        rate_limit_backend="memory",
        rate_limit_per_minute=1,
        rate_limit_per_hour=100,
    )
    response = _mock_httpx_response()
    client_cm = _mock_httpx_client(response)
    client_id = build_client_id("test-key", "203.0.113.10")
    token = client_id_ctx.set(client_id)

    try:
        with patch("app.services.fetcher.httpx.AsyncClient", return_value=client_cm):
            await fetch_url_content("https://example.com/page", settings)

            with pytest.raises(FetchError, match="Rate limit exceeded"):
                await fetch_url_content("https://example.com/other", settings)
    finally:
        client_id_ctx.reset(token)

    assert client_cm.__aenter__.await_count == 1


@pytest.mark.asyncio
async def test_fetch_url_content_skips_rate_limit_for_cache_hits(settings_without_env):
    settings = settings_without_env(
        cache_enabled=True,
        cache_backend="memory",
        cache_ttl_seconds=60,
        cache_max_entries=10,
        rate_limit_enabled=True,
        rate_limit_backend="memory",
        rate_limit_per_minute=1,
        rate_limit_per_hour=100,
    )
    response = _mock_httpx_response()
    client_cm = _mock_httpx_client(response)
    client_id = build_client_id("test-key", "203.0.113.10")
    token = client_id_ctx.set(client_id)

    try:
        with patch("app.services.fetcher.httpx.AsyncClient", return_value=client_cm):
            await fetch_url_content("https://example.com/page", settings)
            await fetch_url_content("https://example.com/page", settings)
    finally:
        client_id_ctx.reset(token)

    assert client_cm.__aenter__.await_count == 1
