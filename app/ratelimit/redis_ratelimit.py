import time

from app.ratelimit.base import RateLimitExceeded

_KEY_PREFIX = "website-reader:ratelimit:"

try:
    import redis.asyncio as redis_async
except ImportError:
    redis_async = None


class RedisRateLimiter:
    def __init__(
        self,
        redis_url: str,
        per_minute: int,
        per_hour: int,
    ) -> None:
        if redis_async is None:
            raise RuntimeError(
                "Redis rate limit backend requires the 'redis' package. "
                "Install it with: pip install redis"
            )

        self._client = redis_async.from_url(redis_url, decode_responses=True)
        self._per_minute = per_minute
        self._per_hour = per_hour

    async def acquire(self, client_id: str) -> None:
        now = time.time()
        minute_bucket = int(now // 60)
        hour_bucket = int(now // 3600)
        minute_key = f"{_KEY_PREFIX}{client_id}:m:{minute_bucket}"
        hour_key = f"{_KEY_PREFIX}{client_id}:h:{hour_bucket}"

        minute_count = await self._client.incr(minute_key)
        if minute_count == 1:
            await self._client.expire(minute_key, 120)

        if minute_count > self._per_minute:
            retry_after = await self._client.ttl(minute_key)
            raise RateLimitExceeded(retry_after if retry_after and retry_after > 0 else 60)

        hour_count = await self._client.incr(hour_key)
        if hour_count == 1:
            await self._client.expire(hour_key, 7200)

        if hour_count > self._per_hour:
            retry_after = await self._client.ttl(hour_key)
            raise RateLimitExceeded(retry_after if retry_after and retry_after > 0 else 3600)
