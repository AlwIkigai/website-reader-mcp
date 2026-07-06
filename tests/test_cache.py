import json
from unittest.mock import AsyncMock

import pytest

from app.cache.redis_cache import RedisUrlCache
from app.services.fetch_types import FetchResponse


@pytest.mark.asyncio
async def test_redis_cache_round_trip(monkeypatch):
    stored: dict[str, str] = {}

    async def fake_get(key: str):
        return stored.get(key)

    async def fake_set(key: str, value: str, ex: int | None = None):
        stored[key] = value

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=fake_get)
    fake_client.set = AsyncMock(side_effect=fake_set)

    monkeypatch.setattr(
        "app.cache.redis_cache.redis_async.from_url",
        lambda *args, **kwargs: fake_client,
    )

    cache = RedisUrlCache(redis_url="redis://localhost:6379/0", ttl_seconds=120)
    entry = FetchResponse(
        url="https://example.com",
        final_url="https://example.com/",
        status_code=200,
        content_type="text/html; charset=utf-8",
        body="<p>redis</p>",
    )

    await cache.set("https://example.com", entry)
    cached = await cache.get("https://example.com")

    assert cached == entry
    assert json.loads(stored["website-reader:url:https://example.com"])["body"] == "<p>redis</p>"
