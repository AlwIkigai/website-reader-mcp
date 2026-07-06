from urllib.parse import urlparse

import httpx

from app.cache import get_url_cache
from app.config import Settings, get_settings
from app.ratelimit import get_rate_limiter
from app.ratelimit.base import RateLimitExceeded
from app.ratelimit.context import get_client_id
from app.services.fetch_types import FetchResponse, ValidatedURL
from app.ssrf import SSRFProtectedTransport, get_resolver
from app.ssrf.errors import SSRFError, URLValidationError
from app.ssrf.ip_rules import (
    BLOCKED_HOSTNAMES,
    is_blocked_ip,
    is_ip_literal,
    normalize_hostname,
    try_parse_ip,
)

__all__ = [
    "FetchError",
    "SSRFError",
    "URLValidationError",
    "fetch_url_content",
    "validate_url",
]

SUPPORTED_CONTENT_PREFIXES = ("text/html", "text/plain", "application/xhtml+xml")


class FetchError(Exception):
    """Raised when a page cannot be fetched."""


def validate_url(url: str, settings: Settings | None = None) -> ValidatedURL:
    """Validate a URL syntactically and reject obviously unsafe targets.

    This is a fast, synchronous pre-flight check (schemes, blocked hostnames, and
    IP literals). DNS-based validation and connection pinning happen at fetch
    time via :class:`app.ssrf.SSRFProtectedTransport`.
    """
    settings = settings or get_settings()
    cleaned = url.strip()

    if not cleaned:
        raise URLValidationError("URL is required.")

    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()

    if scheme not in settings.allowed_scheme_set:
        allowed = ", ".join(sorted(settings.allowed_scheme_set))
        raise URLValidationError(f"Only {allowed} URLs are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL must include a hostname.")

    normalized_host = normalize_hostname(hostname)
    if normalized_host in BLOCKED_HOSTNAMES:
        raise URLValidationError("Localhost and internal hostnames are not allowed.")

    if is_ip_literal(normalized_host):
        ip_address = try_parse_ip(normalized_host)
        if ip_address is None:
            raise URLValidationError("URL contains an invalid IP address.")

        if is_blocked_ip(ip_address):
            raise URLValidationError("Private, loopback, and internal IP addresses are not allowed.")

    if not parsed.netloc:
        raise URLValidationError("Malformed URL.")

    return ValidatedURL(url=cleaned, scheme=scheme, hostname=normalized_host)


async def fetch_url_content(url: str, settings: Settings | None = None) -> FetchResponse:
    settings = settings or get_settings()

    try:
        validated = validate_url(url, settings)
    except URLValidationError as exc:
        raise FetchError(str(exc)) from exc

    cache = get_url_cache(settings)
    if settings.cache_enabled:
        cached = await cache.get(validated.url)
        if cached is not None:
            return cached

    if settings.rate_limit_enabled:
        limiter = get_rate_limiter(settings)
        try:
            await limiter.acquire(get_client_id())
        except RateLimitExceeded as exc:
            raise FetchError(str(exc)) from exc

    headers = {"User-Agent": settings.user_agent}

    transport = None
    if settings.ssrf_dns_validation_enabled:
        transport = SSRFProtectedTransport(get_resolver(settings))

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=settings.max_redirects,
            timeout=settings.request_timeout_seconds,
            headers=headers,
            transport=transport,
        ) as client:
            async with client.stream("GET", validated.url) as response:
                content_type = response.headers.get("content-type", "application/octet-stream")
                media_type = content_type.split(";", 1)[0].strip().lower()

                if not media_type.startswith(SUPPORTED_CONTENT_PREFIXES):
                    raise FetchError(
                        f"Unsupported content type: {content_type}. "
                        "Only HTML and plain text responses are supported."
                    )

                chunks: list[bytes] = []
                total_bytes = 0

                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > settings.max_html_bytes:
                        raise FetchError(
                            f"Response exceeded the maximum size of {settings.max_html_bytes} bytes."
                        )
                    chunks.append(chunk)

                body_bytes = b"".join(chunks)

                try:
                    body = body_bytes.decode(response.encoding or "utf-8")
                except UnicodeDecodeError:
                    body = body_bytes.decode("utf-8", errors="replace")

                fetched = FetchResponse(
                    url=validated.url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                    body=body,
                )

                if settings.cache_enabled:
                    await cache.set(validated.url, fetched)

                return fetched
    except FetchError:
        raise
    except URLValidationError as exc:
        raise FetchError(str(exc)) from exc
    except httpx.TooManyRedirects as exc:
        raise FetchError("Too many redirects while fetching the URL.") from exc
    except httpx.TimeoutException as exc:
        raise FetchError(
            f"Request timed out after {settings.request_timeout_seconds} seconds."
        ) from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"Failed to fetch URL: {exc}") from exc
