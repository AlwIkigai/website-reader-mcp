import pytest

from app.services.host_allowlist import (
    HostAllowlistError,
    host_header_matches_allowlist,
    normalize_host,
    parse_host_header,
    parse_mcp_allowed_hosts,
)


def test_parse_empty_allowlist_is_disabled():
    allowlist = parse_mcp_allowed_hosts("")

    assert allowlist.enabled is False
    assert allowlist.allow_all is True
    assert host_header_matches_allowlist("example.com", allowlist) is True


def test_parse_wildcard_allows_all_hosts():
    allowlist = parse_mcp_allowed_hosts("*")

    assert allowlist.enabled is True
    assert allowlist.allow_all is True
    assert host_header_matches_allowlist("example.com:443", allowlist) is True


def test_exact_host_matching_ignores_port():
    allowlist = parse_mcp_allowed_hosts("example.com,docs.python.org")

    assert host_header_matches_allowlist("example.com", allowlist) is True
    assert host_header_matches_allowlist("example.com:443", allowlist) is True
    assert host_header_matches_allowlist("www.example.com", allowlist) is False


def test_subdomain_wildcard_matching():
    allowlist = parse_mcp_allowed_hosts("*.example.com")

    assert host_header_matches_allowlist("api.example.com", allowlist) is True
    assert host_header_matches_allowlist("api.example.com:8443", allowlist) is True
    assert host_header_matches_allowlist("example.com", allowlist) is False
    assert host_header_matches_allowlist("evil-example.com", allowlist) is False


def test_port_wildcard_matching():
    allowlist = parse_mcp_allowed_hosts("localhost:*")

    assert host_header_matches_allowlist("localhost:8001", allowlist) is True
    assert host_header_matches_allowlist("localhost", allowlist) is False


def test_idna_normalization_matches_unicode_hosts():
    allowlist = parse_mcp_allowed_hosts("münchen.de")

    assert host_header_matches_allowlist("münchen.de", allowlist) is True
    assert host_header_matches_allowlist(normalize_host("münchen.de"), allowlist) is True


def test_parse_host_header_handles_ipv6_with_port():
    hostname, port = parse_host_header("[::1]:8001")

    assert hostname == "::1"
    assert port == 8001


@pytest.mark.parametrize(
    "entry",
    [
        "*.",
        "*.com",
        "https://example.com",
        "example.com/path",
        "user@example.com",
        "example.com:443",
        "*foo",
    ],
)
def test_parse_rejects_invalid_allowlist_entries(entry: str):
    with pytest.raises(HostAllowlistError):
        parse_mcp_allowed_hosts(entry)


def test_settings_rejects_invalid_mcp_allowed_hosts(settings_without_env):
    with pytest.raises(ValueError, match="Subdomain wildcard"):
        settings_without_env(mcp_allowed_hosts="*.")


def test_restrictive_allowlist_denies_unlisted_host(settings_without_env):
    settings = settings_without_env(mcp_allowed_hosts="allowed.example")

    allowlist = settings.mcp_host_allowlist
    assert host_header_matches_allowlist("allowed.example", allowlist) is True
    assert host_header_matches_allowlist("blocked.example", allowlist) is False
