from typing import Protocol


class RateLimitExceeded(Exception):
    """Raised when a client exceeds configured fetch rate limits."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(f"Rate limit exceeded. Retry after {self.retry_after_seconds} seconds.")


class RateLimiter(Protocol):
    async def acquire(self, client_id: str) -> None:
        """Reserve one fetch slot or raise RateLimitExceeded."""
        ...
