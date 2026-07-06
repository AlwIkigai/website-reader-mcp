from dataclasses import dataclass


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    hostname: str


@dataclass(frozen=True)
class FetchResponse:
    url: str
    final_url: str
    status_code: int
    content_type: str
    body: str
