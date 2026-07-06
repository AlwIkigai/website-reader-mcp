"""DNS resolution hardened against SSRF.

Resolves hostnames concurrently across several independent resolvers (the
system resolver plus public resolvers such as Cloudflare and Google), then
validates every returned address. If *any* resolver returns a blocked address
the hostname is rejected. This makes DNS-rebinding and split-horizon tricks much
harder, because an attacker would have to poison every resolver simultaneously.

Very low per-query timeouts are used so a slow or unreachable resolver cannot
stall a request; other resolvers still provide answers.
"""

import asyncio
import ipaddress
from dataclasses import dataclass

import dns.asyncresolver
import dns.exception
import dns.resolver

from app.ssrf.errors import SSRFError
from app.ssrf.ip_rules import is_blocked_ip

SYSTEM_RESOLVER = "system"


@dataclass(frozen=True)
class ResolutionResult:
    hostname: str
    addresses: tuple[str, ...]

    @property
    def primary(self) -> str:
        return self.addresses[0]


class DNSResolver:
    """Resolve and validate hostnames across multiple DNS resolvers."""

    def __init__(
        self,
        resolvers: list[str],
        timeout_seconds: float,
        max_addresses: int = 16,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("DNS timeout must be positive.")

        self._timeout = timeout_seconds
        self._max_addresses = max_addresses
        self._resolvers = [self._build_resolver(spec) for spec in resolvers]

        if not self._resolvers:
            raise ValueError("At least one DNS resolver must be configured.")

    def _build_resolver(self, spec: str) -> dns.asyncresolver.Resolver:
        spec = spec.strip().lower()
        use_system = spec == SYSTEM_RESOLVER

        try:
            resolver = dns.asyncresolver.Resolver(configure=use_system)
        except dns.resolver.NoResolverConfiguration:
            resolver = dns.asyncresolver.Resolver(configure=False)

        if not use_system:
            resolver.nameservers = [spec]

        # Per-server timeout and overall lifetime are both kept low. Resolvers
        # are queried concurrently, so the total added latency is bounded by a
        # single timeout window regardless of how many resolvers are configured.
        resolver.timeout = self._timeout
        resolver.lifetime = self._timeout
        return resolver

    async def _query(
        self,
        resolver: dns.asyncresolver.Resolver,
        hostname: str,
        rdtype: str,
    ) -> set[str]:
        try:
            answer = await resolver.resolve(
                hostname,
                rdtype,
                raise_on_no_answer=False,
            )
        except dns.exception.DNSException:
            return set()

        if answer.rrset is None:
            return set()

        return {record.address for record in answer}

    async def resolve(self, hostname: str) -> set[str]:
        """Return the union of A/AAAA addresses across all resolvers."""
        tasks = [
            self._query(resolver, hostname, rdtype)
            for resolver in self._resolvers
            for rdtype in ("A", "AAAA")
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        addresses: set[str] = set()
        for result in results:
            if isinstance(result, set):
                addresses |= result

        return addresses

    async def resolve_and_validate(self, hostname: str) -> ResolutionResult:
        """Resolve ``hostname`` and reject it if any resolved IP is unsafe.

        Returns the validated public addresses (IPv4 first for connectivity),
        raising :class:`SSRFError` if resolution fails or any address is blocked.
        """
        addresses = await self.resolve(hostname)

        if not addresses:
            raise SSRFError(f"Could not resolve hostname: {hostname}")

        parsed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                raise SSRFError(f"Resolver returned an invalid address for {hostname}.")

            if is_blocked_ip(ip):
                raise SSRFError(
                    "Hostname resolves to a private, loopback, or otherwise "
                    "blocked IP address."
                )

            parsed.append(ip)

        parsed.sort(key=lambda ip: (ip.version, ip.packed))
        ordered = tuple(str(ip) for ip in parsed[: self._max_addresses])
        return ResolutionResult(hostname=hostname, addresses=ordered)
