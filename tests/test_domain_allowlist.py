import pytest

from app.services.domain_allowlist import (
    DomainAllowlistError,
    hostname_matches_allowlist,
    normalize_domain,
    parse_allowed_domains,
)
from app.services.fetcher import URLValidationError, validate_url


def test_parse_empty_allowlist_denies_by_default():
    allowlist = parse_allowed_domains("")

    assert allowlist.allow_all is False
    assert allowlist.is_restrictive is True
    assert hostname_matches_allowlist("example.com", allowlist) is False


def test_parse_wildcard_allows_all_domains():
    allowlist = parse_allowed_domains("*")

    assert allowlist.allow_all is True
    assert hostname_matches_allowlist("example.com", allowlist) is True
    assert hostname_matches_allowlist("anything.evil", allowlist) is True


def test_exact_domain_matching():
    allowlist = parse_allowed_domains("example.com,docs.python.org")

    assert hostname_matches_allowlist("example.com", allowlist) is True
    assert hostname_matches_allowlist("docs.python.org", allowlist) is True
    assert hostname_matches_allowlist("www.example.com", allowlist) is False
    assert hostname_matches_allowlist("notexample.com", allowlist) is False


def test_subdomain_wildcard_matching():
    allowlist = parse_allowed_domains("*.example.com")

    assert hostname_matches_allowlist("api.example.com", allowlist) is True
    assert hostname_matches_allowlist("deep.nested.example.com", allowlist) is True
    assert hostname_matches_allowlist("example.com", allowlist) is False
    assert hostname_matches_allowlist("notexample.com", allowlist) is False
    assert hostname_matches_allowlist("evil-example.com", allowlist) is False
    assert hostname_matches_allowlist("example.com.evil.com", allowlist) is False


def test_idna_normalization_matches_unicode_hosts():
    allowlist = parse_allowed_domains("münchen.de")

    assert hostname_matches_allowlist("münchen.de", allowlist) is True
    assert hostname_matches_allowlist(normalize_domain("münchen.de"), allowlist) is True


def test_ip_literals_never_match_restrictive_allowlist():
    allowlist = parse_allowed_domains("example.com")

    assert hostname_matches_allowlist("8.8.8.8", allowlist) is False
    assert hostname_matches_allowlist("127.0.0.1", allowlist) is False


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
    with pytest.raises(DomainAllowlistError):
        parse_allowed_domains(entry)


def test_settings_rejects_invalid_allowed_domains(settings_without_env):
    with pytest.raises(ValueError, match="Subdomain wildcard"):
        settings_without_env(allowed_domains="*.")


def test_validate_url_rejects_disallowed_domain(settings_without_env):
    settings = settings_without_env(allowed_domains="allowed.example")

    with pytest.raises(URLValidationError, match="not on the allowlist"):
        validate_url("https://blocked.example/page", settings)


def test_validate_url_allows_exact_and_subdomain_entries(settings_without_env):
    settings = settings_without_env(
        allowed_domains="allowed.example,*.trusted.org",
    )

    exact = validate_url("https://allowed.example/page", settings)
    subdomain = validate_url("https://api.trusted.org/docs", settings)

    assert exact.hostname == "allowed.example"
    assert subdomain.hostname == "api.trusted.org"


def test_validate_url_denies_public_domain_when_allowlist_empty(settings_without_env):
    settings = settings_without_env(allowed_domains="")

    with pytest.raises(URLValidationError, match="not on the allowlist"):
        validate_url("https://example.com", settings)


def test_validate_url_allows_all_with_wildcard(settings_without_env):
    settings = settings_without_env(allowed_domains="*")

    validated = validate_url("https://any-domain.test/article", settings)

    assert validated.hostname == "any-domain.test"
