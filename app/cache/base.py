from typing import Protocol

from app.services.fetch_types import FetchResponse


class UrlCache(Protocol):
    async def get(self, key: str) -> FetchResponse | None:
        ...

    async def set(self, key: str, value: FetchResponse) -> None:
        ...
