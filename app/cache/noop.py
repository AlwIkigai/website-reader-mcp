from app.services.fetch_types import FetchResponse


class NoOpUrlCache:
    async def get(self, key: str) -> FetchResponse | None:
        return None

    async def set(self, key: str, value: FetchResponse) -> None:
        return None
