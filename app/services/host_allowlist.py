"""MCP client host allowlist parsing and Host-header matching."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

import idna

WILDCARD_ALL = "*"
WILDCARD_SUBDOMAIN_PREFIX = "*."
PORT_WILDCARD_SUFFIX = ":*"

_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class HostAllowlistError(ValueError):
    """Raised when MCP_ALLOWED_HOSTS contains invalid entries."""


@dataclass(frozen=True)
class HostAllowlist:
    enabled: bool
    allow_all: bool
    exact_hosts: frozenset[str]
    subdomain_bases: frozenset[str]
    port_wildcard_hosts: frozenset[str]

    @property
    def is_restrictive(self) -> bool:
        return self.enabled and not self.allow_all


def normalize_host(hostname: str) -> str:
    """Normalize a hostname to lowercase punycode (IDNA UTS #46)."""
    cleaned = hostname.strip().lower().rstrip(".")
    if not cleaned:
        raise HostAllowlistError("Host entries cannot be empty.")

    try:
        return ipaddress.ip_address(cleaned).compressed
    except ValueError:
        pass

    try:
        return idna.encode(cleaned, uts46=True).decode("ascii")
    except idna.IDNAError as exc:
        raise HostAllowlistError(f"Invalid host entry: {hostname!r}") from exc


def _validate_host_labels(hostname: str) -> None:
    labels = hostname.split(".")
    if not labels or any(not label for label in labels):
        raise HostAllowlistError(f"Invalid host entry: {hostname!r}")

    for label in labels:
        if label.startswith("xn--"):
            continue
        if not _HOST_LABEL_RE.match(label):
            raise HostAllowlistError(f"Invalid host entry: {hostname!r}")


def _reject_unsafe_host_entry(entry: str) -> None:
    if any(char in entry for char in ("/", "\\", "@", "?", "#")):
        raise HostAllowlistError(
            f"Allowlist entries must be bare hostnames or wildcards, not URLs: {entry!r}"
        )

    if ":" in entry and not entry.endswith(PORT_WILDCARD_SUFFIX):
        raise HostAllowlistError(
            f"Port-specific entries must use the host:* form, e.g. localhost:*: {entry!r}"
        )


def parse_mcp_allowed_hosts(raw: str) -> HostAllowlist:
    """Parse MCP_ALLOWED_HOSTS into host-matching rules."""
    if not raw.strip():
        return HostAllowlist(
            enabled=False,
            allow_all=True,
            exact_hosts=frozenset(),
            subdomain_bases=frozenset(),
            port_wildcard_hosts=frozenset(),
        )

    entries = [part.strip() for part in raw.split(",") if part.strip()]
    if WILDCARD_ALL in entries:
        return HostAllowlist(
            enabled=True,
            allow_all=True,
            exact_hosts=frozenset(),
            subdomain_bases=frozenset(),
            port_wildcard_hosts=frozenset(),
        )

    exact_hosts: set[str] = set()
    subdomain_bases: set[str] = set()
    port_wildcard_hosts: set[str] = set()

    for entry in entries:
        _reject_unsafe_host_entry(entry)

        if entry == WILDCARD_ALL:
            continue

        if entry.endswith(PORT_WILDCARD_SUFFIX):
            base = entry[: -len(PORT_WILDCARD_SUFFIX)]
            if not base:
                raise HostAllowlistError(f"Invalid port wildcard entry: {entry!r}")

            normalized = normalize_host(base)
            _validate_host_labels(normalized)
            port_wildcard_hosts.add(normalized)
            continue

        if entry.startswith(WILDCARD_SUBDOMAIN_PREFIX):
            base = entry[len(WILDCARD_SUBDOMAIN_PREFIX) :]
            if not base or "." not in base:
                raise HostAllowlistError(
                    f"Subdomain wildcard must target a registrable domain, e.g. *.example.com: {entry!r}"
                )

            normalized_base = normalize_host(base)
            _validate_host_labels(normalized_base)
            subdomain_bases.add(normalized_base)
            continue

        if entry.startswith("*"):
            raise HostAllowlistError(
                f"Unsupported wildcard pattern {entry!r}. Use * for all hosts or *.example.com for subdomains."
            )

        normalized = normalize_host(entry)
        _validate_host_labels(normalized)
        exact_hosts.add(normalized)

    return HostAllowlist(
        enabled=True,
        allow_all=False,
        exact_hosts=frozenset(exact_hosts),
        subdomain_bases=frozenset(subdomain_bases),
        port_wildcard_hosts=frozenset(port_wildcard_hosts),
    )


def parse_host_header(host_header: str) -> tuple[str, int | None]:
    """Split a Host header value into a normalized hostname and optional port."""
    cleaned = host_header.strip().lower()
    if not cleaned:
        raise HostAllowlistError("Host header is empty.")

    if cleaned.startswith("["):
        closing = cleaned.find("]")
        if closing == -1:
            return normalize_host(cleaned), None

        hostname = normalize_host(cleaned[1:closing])
        remainder = cleaned[closing + 1 :]
        if remainder.startswith(":"):
            return hostname, int(remainder[1:])
        return hostname, None

    if ":" in cleaned:
        hostname, _, port_text = cleaned.rpartition(":")
        return normalize_host(hostname), int(port_text)

    return normalize_host(cleaned), None


def host_header_matches_allowlist(host_header: str, allowlist: HostAllowlist) -> bool:
    """Return True when the request Host header is permitted."""
    if not allowlist.enabled or allowlist.allow_all:
        return True

    hostname, port = parse_host_header(host_header)

    if hostname in allowlist.exact_hosts:
        return True

    if port is not None and hostname in allowlist.port_wildcard_hosts:
        return True

    for base in allowlist.subdomain_bases:
        suffix = f".{base}"
        if hostname.endswith(suffix) and len(hostname) > len(suffix):
            return True

    return False
