"""IP address and hostname classification for SSRF protection.

Centralizes the logic that decides whether a given IP address or hostname is
safe to connect to. This is intentionally conservative: anything that is not
clearly a routable public address is rejected.
"""

import ipaddress

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata",
}

# IPv4 ranges that must never be reached. ``ipaddress`` covers most of these via
# is_private/is_reserved, but several cloud/SSRF-relevant ranges are not flagged
# by the standard library, so we enumerate them explicitly.
_BLOCKED_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",          # "this" network
        "10.0.0.0/8",         # RFC1918 private
        "100.64.0.0/10",      # RFC6598 carrier-grade NAT
        "127.0.0.0/8",        # loopback
        "169.254.0.0/16",     # link-local (incl. 169.254.169.254 metadata)
        "172.16.0.0/12",      # RFC1918 private
        "192.0.0.0/24",       # IETF protocol assignments
        "192.0.2.0/24",       # TEST-NET-1
        "192.88.99.0/24",     # deprecated 6to4 relay anycast
        "192.168.0.0/16",     # RFC1918 private
        "198.18.0.0/15",      # benchmarking
        "198.51.100.0/24",    # TEST-NET-2
        "203.0.113.0/24",     # TEST-NET-3
        "224.0.0.0/4",        # multicast
        "240.0.0.0/4",        # reserved for future use (incl. 255.255.255.255)
    )
)

_BLOCKED_IPV6_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "::/128",             # unspecified
        "::1/128",            # loopback
        "::ffff:0:0/96",      # IPv4-mapped (handled explicitly too)
        "64:ff9b::/96",       # NAT64 (handled explicitly too)
        "100::/64",           # discard-only
        "2001:db8::/32",      # documentation
        "2002::/16",          # 6to4 (handled explicitly too)
        "fc00::/7",           # unique local addresses
        "fe80::/10",          # link-local
        "ff00::/8",           # multicast
    )
)

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_SIXTOFOUR_PREFIX = ipaddress.ip_network("2002::/16")


def normalize_hostname(hostname: str) -> str:
    return hostname.strip().lower().rstrip(".")


def try_parse_ip(hostname: str) -> IPAddress | None:
    host = hostname
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def is_ip_literal(hostname: str) -> bool:
    return try_parse_ip(hostname) is not None


def is_blocked_ip(address: IPAddress) -> bool:
    """Return True when connecting to ``address`` would be unsafe.

    Handles IPv4, IPv6, and IPv6-embedded IPv4 (mapped, NAT64, 6to4) so that an
    attacker cannot smuggle a private IPv4 target through an IPv6 encoding.
    """
    if isinstance(address, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(address)
        if embedded is not None and is_blocked_ip(embedded):
            return True

    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return True

    if isinstance(address, ipaddress.IPv4Address):
        return any(address in network for network in _BLOCKED_IPV4_NETWORKS)

    return any(address in network for network in _BLOCKED_IPV6_NETWORKS)


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped

    if address in _NAT64_PREFIX:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)

    if address in _SIXTOFOUR_PREFIX:
        return ipaddress.IPv4Address((int(address) >> 80) & 0xFFFFFFFF)

    return None
