import ipaddress
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.ssrf.errors import SSRFError
from app.ssrf.ip_rules import is_blocked_ip
from app.ssrf.resolver import DNSResolver
from app.ssrf.transport import SSRFProtectedTransport


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.0.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",       # carrier-grade NAT
        "0.0.0.0",
        "255.255.255.255",
        "198.18.0.1",       # benchmarking
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",         # IPv4-mapped loopback
        "64:ff9b::7f00:1",          # NAT64 embeds 127.0.0.1
        "2002:c0a8:0101::",         # 6to4 embeds 192.168.1.1
    ],
)
def test_is_blocked_ip_blocks_unsafe_addresses(address: str):
    assert is_blocked_ip(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize(
    "address",
    ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"],
)
def test_is_blocked_ip_allows_public_addresses(address: str):
    assert is_blocked_ip(ipaddress.ip_address(address)) is False


def _resolver() -> DNSResolver:
    # Use a fixed public resolver spec so construction never reads resolv.conf.
    return DNSResolver(resolvers=["1.1.1.1"], timeout_seconds=1.0)


@pytest.mark.asyncio
async def test_resolve_and_validate_returns_public_addresses_ipv4_first():
    resolver = _resolver()
    resolver.resolve = AsyncMock(
        return_value={"93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"}
    )

    result = await resolver.resolve_and_validate("example.com")

    assert result.primary == "93.184.216.34"
    assert set(result.addresses) == {
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    }


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_when_any_ip_is_private():
    resolver = _resolver()
    resolver.resolve = AsyncMock(return_value={"93.184.216.34", "10.0.0.5"})

    with pytest.raises(SSRFError, match="private"):
        await resolver.resolve_and_validate("rebind.example.com")


@pytest.mark.asyncio
async def test_resolve_and_validate_rejects_unresolvable_hostname():
    resolver = _resolver()
    resolver.resolve = AsyncMock(return_value=set())

    with pytest.raises(SSRFError, match="Could not resolve"):
        await resolver.resolve_and_validate("does-not-exist.invalid")


@pytest.mark.asyncio
async def test_resolve_unions_answers_across_resolvers():
    resolver = DNSResolver(resolvers=["1.1.1.1", "8.8.8.8"], timeout_seconds=1.0)
    # Task order is (r0 A, r0 AAAA, r1 A, r1 AAAA).
    resolver._query = AsyncMock(
        side_effect=[{"1.2.3.4"}, set(), {"5.6.7.8"}, {"2001:db8::1"}]
    )

    addresses = await resolver.resolve("example.com")

    assert addresses == {"1.2.3.4", "5.6.7.8", "2001:db8::1"}


@pytest.mark.asyncio
async def test_transport_rejects_blocked_ip_literal():
    transport = SSRFProtectedTransport(_resolver())
    request = httpx.Request("GET", "http://169.254.169.254/latest/meta-data")

    with pytest.raises(SSRFError):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_transport_pins_validated_ip_and_preserves_sni():
    resolver = _resolver()
    resolver.resolve = AsyncMock(return_value={"93.184.216.34"})
    transport = SSRFProtectedTransport(resolver)
    request = httpx.Request("GET", "https://example.com/page")

    captured = {}

    async def _fake_super(self, req):
        captured["host"] = req.url.host
        captured["sni"] = req.extensions.get("sni_hostname")
        return httpx.Response(200)

    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super):
        await transport.handle_async_request(request)

    assert captured["host"] == "93.184.216.34"
    assert captured["sni"] == "example.com"
    # URL is restored so redirect resolution uses the real hostname.
    assert request.url.host == "example.com"


@pytest.mark.asyncio
async def test_transport_allows_public_ip_literal_without_dns():
    resolver = _resolver()
    resolver.resolve = AsyncMock(side_effect=AssertionError("DNS must not run"))
    transport = SSRFProtectedTransport(resolver)
    request = httpx.Request("GET", "http://93.184.216.34/")

    async def _fake_super(self, req):
        return httpx.Response(200)

    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _fake_super):
        response = await transport.handle_async_request(request)

    assert response.status_code == 200


def test_settings_resolver_list_parses_and_dedupes():
    settings = Settings(
        mcp_api_key="test-key",
        ssrf_dns_resolvers="system, 1.1.1.1 ,1.1.1.1, 8.8.8.8",
    )
    assert settings.ssrf_dns_resolver_list == ["system", "1.1.1.1", "8.8.8.8"]


def test_settings_resolver_list_defaults_to_system_when_empty():
    settings = Settings(mcp_api_key="test-key", ssrf_dns_resolvers="  ,  ")
    assert settings.ssrf_dns_resolver_list == ["system"]
