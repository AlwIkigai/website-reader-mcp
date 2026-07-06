"""An httpx transport that enforces SSRF protection at connection time.

Validating DNS *before* handing the URL to httpx is not enough on its own: httpx
would resolve the hostname again when it opens the socket, leaving a window for
DNS rebinding (the name resolves to a safe IP during validation and to an
internal IP a moment later). This transport closes that window by resolving and
validating the hostname itself, then pinning the connection to the exact
validated IP while preserving the original Host header and TLS SNI/certificate
verification.

Because every request flows through the transport, redirect targets are
validated too.
"""

import httpx

from app.ssrf.errors import SSRFError
from app.ssrf.ip_rules import is_blocked_ip, try_parse_ip
from app.ssrf.resolver import DNSResolver


class SSRFProtectedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, resolver: DNSResolver, **kwargs) -> None:
        super().__init__(**kwargs)
        self._resolver = resolver

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host

        literal = try_parse_ip(host)
        if literal is not None:
            if is_blocked_ip(literal):
                raise SSRFError(
                    "Private, loopback, and internal IP addresses are not allowed."
                )
            return await super().handle_async_request(request)

        result = await self._resolver.resolve_and_validate(host)
        pinned_ip = result.primary

        # Preserve certificate verification and SNI against the real hostname
        # even though we connect straight to the validated IP.
        request.extensions["sni_hostname"] = host

        original_url = request.url
        request.url = original_url.copy_with(host=pinned_ip)
        try:
            return await super().handle_async_request(request)
        finally:
            # Restore the original URL so httpx resolves relative redirect
            # targets against the real hostname rather than the pinned IP.
            request.url = original_url
