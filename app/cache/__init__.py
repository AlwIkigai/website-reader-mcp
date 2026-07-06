from functools import lru_cache

from app.cache.memory import MemoryUrlCache
from app.cache.noop import NoOpUrlCache
from app.cache.redis_cache import RedisUrlCache
from app.config import Settings, get_settings


@lru_cache
def _build_url_cache(
    enabled: bool,
    backend: str,
    ttl_seconds: int,
    max_entries: int,
    redis_url: str,
):
    if not enabled:
        return NoOpUrlCache()

    if backend == "memory":
        return MemoryUrlCache(ttl_seconds=ttl_seconds, max_entries=max_entries)

    if backend == "redis":
        if not redis_url:
            raise ValueError("REDIS_URL is required when CACHE_BACKEND=redis.")
        return RedisUrlCache(redis_url=redis_url, ttl_seconds=ttl_seconds)

    raise ValueError(f"Unsupported cache backend: {backend!r}. Use 'memory' or 'redis'.")


def get_url_cache(settings: Settings | None = None):
    settings = settings or get_settings()
    return _build_url_cache(
        settings.cache_enabled,
        settings.cache_backend,
        settings.cache_ttl_seconds,
        settings.cache_max_entries,
        settings.redis_url,
    )


def reset_url_cache() -> None:
    _build_url_cache.cache_clear()
