import pytest
from unittest.mock import AsyncMock

from starlette.requests import Request

from app.ratelimit.base import RateLimitExceeded
from app.ratelimit.client_id import build_client_id, get_client_ip
from app.ratelimit.memory import MemoryRateLimiter
from app.ratelimit.redis_ratelimit import RedisRateLimiter


def _request(
    *,
    client_host: str = "203.0.113.10",
    forwarded_for: str | None = None,
    vercel_forwarded_for: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if vercel_forwarded_for is not None:
        headers.append((b"x-vercel-forwarded-for", vercel_forwarded_for.encode()))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/mcp/",
        "headers": headers,
        "query_string": b"",
        "client": (client_host, 12345),
        "server": ("example.com", 443),
        "scheme": "https",
    }
    return Request(scope)


def test_get_client_ip_prefers_vercel_header():
    request = _request(
        client_host="10.0.0.1",
        forwarded_for="198.51.100.1, 10.0.0.1",
        vercel_forwarded_for="203.0.113.5, 10.0.0.1",
    )

    assert get_client_ip(request) == "203.0.113.5"


def test_get_client_ip_uses_forwarded_for_before_socket():
    request = _request(client_host="10.0.0.1", forwarded_for="198.51.100.1, 10.0.0.1")

    assert get_client_ip(request) == "198.51.100.1"


def test_get_client_ip_falls_back_to_socket_client():
    request = _request(client_host="203.0.113.10")

    assert get_client_ip(request) == "203.0.113.10"


def test_build_client_id_hashes_api_key_and_includes_ip():
    first = build_client_id("secret-key", "203.0.113.10")
    second = build_client_id("secret-key", "203.0.113.10")
    different_ip = build_client_id("secret-key", "198.51.100.2")
    different_key = build_client_id("other-key", "203.0.113.10")

    assert first == second
    assert first != different_ip
    assert first != different_key
    assert "secret-key" not in first
    assert first.endswith(":203.0.113.10")


@pytest.mark.asyncio
async def test_memory_rate_limiter_enforces_per_minute_limit():
    limiter = MemoryRateLimiter(per_minute=2, per_hour=100)

    await limiter.acquire("client-a")
    await limiter.acquire("client-a")

    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.acquire("client-a")

    assert exc_info.value.retry_after_seconds >= 1


@pytest.mark.asyncio
async def test_memory_rate_limiter_tracks_clients_separately():
    limiter = MemoryRateLimiter(per_minute=1, per_hour=100)

    await limiter.acquire("client-a")

    await limiter.acquire("client-b")


@pytest.mark.asyncio
async def test_memory_rate_limiter_enforces_per_hour_limit():
    limiter = MemoryRateLimiter(per_minute=100, per_hour=2)

    await limiter.acquire("client-a")
    await limiter.acquire("client-a")

    with pytest.raises(RateLimitExceeded):
        await limiter.acquire("client-a")


@pytest.mark.asyncio
async def test_redis_rate_limiter_uses_redis_counters(monkeypatch):
    counters: dict[str, int] = {}
    expiries: dict[str, int] = {}

    async def fake_incr(key: str) -> int:
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    async def fake_expire(key: str, seconds: int) -> bool:
        expiries[key] = seconds
        return True

    async def fake_ttl(key: str) -> int:
        return 42

    fake_client = AsyncMock()
    fake_client.incr = AsyncMock(side_effect=fake_incr)
    fake_client.expire = AsyncMock(side_effect=fake_expire)
    fake_client.ttl = AsyncMock(side_effect=fake_ttl)

    monkeypatch.setattr(
        "app.ratelimit.redis_ratelimit.redis_async.from_url",
        lambda *args, **kwargs: fake_client,
    )

    limiter = RedisRateLimiter(
        redis_url="redis://localhost:6379/0",
        per_minute=1,
        per_hour=100,
    )

    await limiter.acquire("client-a")

    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.acquire("client-a")

    assert exc_info.value.retry_after_seconds == 42
    assert any(key.startswith("website-reader:ratelimit:client-a:") for key in counters)
