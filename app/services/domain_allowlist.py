"""Domain allowlist parsing and hostname matching."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

import idna

WILDCARD_ALL = "*"
WILDCARD_SUBDOMAIN_PREFIX = "*."

_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DomainAllowlistError(ValueError):
    """Raised when ALLOWED_DOMAINS contains invalid entries."""


@dataclass(frozen=True)
class DomainAllowlist:
    allow_all: bool
    exact_domains: frozenset[str]
    subdomain_bases: frozenset[str]

    @property
    def is_restrictive(self) -> bool:
        return not self.allow_all


def normalize_domain(domain: str) -> str:
    """Normalize a domain label to lowercase punycode (IDNA UTS #46)."""
    cleaned = domain.strip().lower().rstrip(".")
    if not cleaned:
        raise DomainAllowlistError("Domain entries cannot be empty.")

    try:
        return idna.encode(cleaned, uts46=True).decode("ascii")
    except idna.IDNAError as exc:
        raise DomainAllowlistError(f"Invalid domain entry: {domain!r}") from exc


def _validate_domain_labels(domain: str) -> None:
    labels = domain.split(".")
    if len(labels) < 1 or any(not label for label in labels):
        raise DomainAllowlistError(f"Invalid domain entry: {domain!r}")

    for label in labels:
        if label.startswith("xn--"):
            continue
        if not _DOMAIN_LABEL_RE.match(label):
            raise DomainAllowlistError(f"Invalid domain entry: {domain!r}")


def _reject_unsafe_allowlist_entry(entry: str) -> None:
    if any(char in entry for char in ("/", "\\", "@", ":", "?", "#")):
        raise DomainAllowlistError(
            f"Allowlist entries must be bare domains or wildcards, not URLs: {entry!r}"
        )


def parse_allowed_domains(raw: str) -> DomainAllowlist:
    """Parse ALLOWED_DOMAINS into exact hosts and *.base subdomain rules."""
    entries = [part.strip() for part in raw.split(",") if part.strip()]
    if not entries:
        return DomainAllowlist(allow_all=False, exact_domains=frozenset(), subdomain_bases=frozenset())

    if WILDCARD_ALL in entries:
        return DomainAllowlist(allow_all=True, exact_domains=frozenset(), subdomain_bases=frozenset())

    exact_domains: set[str] = set()
    subdomain_bases: set[str] = set()

    for entry in entries:
        _reject_unsafe_allowlist_entry(entry)

        if entry == WILDCARD_ALL:
            continue

        if entry.startswith(WILDCARD_SUBDOMAIN_PREFIX):
            base = entry[len(WILDCARD_SUBDOMAIN_PREFIX) :]
            if not base or "." not in base:
                raise DomainAllowlistError(
                    f"Subdomain wildcard must target a registrable domain, e.g. *.example.com: {entry!r}"
                )

            normalized_base = normalize_domain(base)
            _validate_domain_labels(normalized_base)
            subdomain_bases.add(normalized_base)
            continue

        if entry.startswith("*"):
            raise DomainAllowlistError(
                f"Unsupported wildcard pattern {entry!r}. Use * for all domains or *.example.com for subdomains."
            )

        normalized = normalize_domain(entry)
        _validate_domain_labels(normalized)
        exact_domains.add(normalized)

    return DomainAllowlist(
        allow_all=False,
        exact_domains=frozenset(exact_domains),
        subdomain_bases=frozenset(subdomain_bases),
    )


def _is_ip_literal(hostname: str) -> bool:
    host = hostname
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def hostname_matches_allowlist(hostname: str, allowlist: DomainAllowlist) -> bool:
    """Return True when hostname is permitted by the configured allowlist."""
    if allowlist.allow_all:
        return True

    if not allowlist.exact_domains and not allowlist.subdomain_bases:
        return False

    normalized = normalize_domain(hostname)

    if _is_ip_literal(normalized):
        return False

    if normalized in allowlist.exact_domains:
        return True

    for base in allowlist.subdomain_bases:
        suffix = f".{base}"
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return True

    return False
