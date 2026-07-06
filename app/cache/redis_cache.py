import json

from app.services.fetch_types import FetchResponse

_KEY_PREFIX = "website-reader:url:"

try:
    import redis.asyncio as redis_async
except ImportError:
    redis_async = None


class RedisUrlCache:
    def __init__(self, redis_url: str, ttl_seconds: int) -> None:
        if redis_async is None:
            raise RuntimeError(
                "Redis cache backend requires the 'redis' package. "
                "Install it with: pip install redis"
            )

        self._client = redis_async.from_url(redis_url, decode_responses=True)
        self._ttl_seconds = ttl_seconds

    async def get(self, key: str) -> FetchResponse | None:
        raw = await self._client.get(f"{_KEY_PREFIX}{key}")
        if raw is None:
            return None

        payload = json.loads(raw)
        return FetchResponse(
            url=payload["url"],
            final_url=payload["final_url"],
            status_code=payload["status_code"],
            content_type=payload["content_type"],
            body=payload["body"],
        )

    async def set(self, key: str, value: FetchResponse) -> None:
        payload = json.dumps(
            {
                "url": value.url,
                "final_url": value.final_url,
                "status_code": value.status_code,
                "content_type": value.content_type,
                "body": value.body,
            }
        )
        await self._client.set(f"{_KEY_PREFIX}{key}", payload, ex=self._ttl_seconds)
