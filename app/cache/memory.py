import asyncio

from cachetools import TTLCache

from app.services.fetch_types import FetchResponse


class MemoryUrlCache:
    def __init__(self, ttl_seconds: float, max_entries: int) -> None:
        self._cache: TTLCache[str, FetchResponse] = TTLCache(
            maxsize=max_entries,
            ttl=ttl_seconds,
        )
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> FetchResponse | None:
        async with self._lock:
            return self._cache.get(key)

    async def set(self, key: str, value: FetchResponse) -> None:
        async with self._lock:
            self._cache[key] = value
