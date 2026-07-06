from functools import lru_cache

from app.config import Settings, get_settings
from app.ssrf.errors import SSRFError, URLValidationError
from app.ssrf.resolver import DNSResolver
from app.ssrf.transport import SSRFProtectedTransport

__all__ = [
    "DNSResolver",
    "SSRFError",
    "SSRFProtectedTransport",
    "URLValidationError",
    "get_resolver",
    "reset_resolver",
]


@lru_cache
def _build_resolver(resolvers: tuple[str, ...], timeout_seconds: float) -> DNSResolver:
    return DNSResolver(
        resolvers=list(resolvers),
        timeout_seconds=timeout_seconds,
    )


def get_resolver(settings: Settings | None = None) -> DNSResolver:
    settings = settings or get_settings()
    return _build_resolver(
        tuple(settings.ssrf_dns_resolver_list),
        settings.ssrf_dns_timeout_seconds,
    )


def reset_resolver() -> None:
    _build_resolver.cache_clear()
