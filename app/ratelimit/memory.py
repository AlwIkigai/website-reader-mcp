import asyncio
import time

from app.ratelimit.base import RateLimitExceeded


class MemoryRateLimiter:
    def __init__(self, per_minute: int, per_hour: int) -> None:
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._counters: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, client_id: str) -> None:
        async with self._lock:
            now = time.time()
            minute_bucket = int(now // 60)
            hour_bucket = int(now // 3600)
            minute_key = f"{client_id}:m:{minute_bucket}"
            hour_key = f"{client_id}:h:{hour_bucket}"

            minute_count = self._counters.get(minute_key, 0)
            if minute_count >= self._per_minute:
                retry_after = int(60 - (now % 60)) or 1
                raise RateLimitExceeded(retry_after)

            hour_count = self._counters.get(hour_key, 0)
            if hour_count >= self._per_hour:
                retry_after = int(3600 - (now % 3600)) or 1
                raise RateLimitExceeded(retry_after)

            self._counters[minute_key] = minute_count + 1
            self._counters[hour_key] = hour_count + 1

            self._prune_stale_buckets(minute_bucket, hour_bucket)

    def _prune_stale_buckets(self, minute_bucket: int, hour_bucket: int) -> None:
        stale_keys: list[str] = []
        for key in self._counters:
            if ":m:" in key:
                bucket = int(key.rsplit(":m:", 1)[1])
                if bucket < minute_bucket - 1:
                    stale_keys.append(key)
            elif ":h:" in key:
                bucket = int(key.rsplit(":h:", 1)[1])
                if bucket < hour_bucket - 1:
                    stale_keys.append(key)

        for key in stale_keys:
            self._counters.pop(key, None)
