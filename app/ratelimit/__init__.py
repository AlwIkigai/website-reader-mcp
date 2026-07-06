from functools import lru_cache

from app.config import Settings, get_settings
from app.ratelimit.memory import MemoryRateLimiter
from app.ratelimit.noop import NoOpRateLimiter
from app.ratelimit.redis_ratelimit import RedisRateLimiter


@lru_cache
def _build_rate_limiter(
    enabled: bool,
    backend: str,
    per_minute: int,
    per_hour: int,
    redis_url: str,
):
    if not enabled:
        return NoOpRateLimiter()

    if backend == "memory":
        return MemoryRateLimiter(per_minute=per_minute, per_hour=per_hour)

    if backend == "redis":
        if not redis_url:
            raise ValueError("REDIS_URL is required when RATE_LIMIT_BACKEND=redis.")
        return RedisRateLimiter(
            redis_url=redis_url,
            per_minute=per_minute,
            per_hour=per_hour,
        )

    raise ValueError(f"Unsupported rate limit backend: {backend!r}. Use 'memory' or 'redis'.")


def get_rate_limiter(settings: Settings | None = None):
    settings = settings or get_settings()
    return _build_rate_limiter(
        settings.rate_limit_enabled,
        settings.rate_limit_backend,
        settings.rate_limit_per_minute,
        settings.rate_limit_per_hour,
        settings.redis_url,
    )


def reset_rate_limiter() -> None:
    _build_rate_limiter.cache_clear()
