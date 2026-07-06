class NoOpRateLimiter:
    async def acquire(self, client_id: str) -> None:
        return None
