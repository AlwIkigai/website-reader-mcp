from functools import cached_property, lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.domain_allowlist import DomainAllowlistError, parse_allowed_domains


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    mcp_api_key: str = Field(alias="MCP_API_KEY")
    app_env: str = Field(default="local", alias="APP_ENV")
    request_timeout_seconds: float = Field(default=12.0, alias="REQUEST_TIMEOUT_SECONDS")
    max_response_chars: int = Field(default=12000, alias="MAX_RESPONSE_CHARS")
    max_html_bytes: int = Field(default=2_000_000, alias="MAX_HTML_BYTES")
    allowed_schemes: str = Field(default="https,http", alias="ALLOWED_SCHEMES")
    allowed_domains: str = Field(default="", alias="ALLOWED_DOMAINS")
    mcp_allowed_hosts: str = Field(default="", alias="MCP_ALLOWED_HOSTS")
    mcp_allowed_origins: str = Field(default="", alias="MCP_ALLOWED_ORIGINS")

    user_agent: str = "WebsiteReaderMCP/0.1"
    max_redirects: int = 5
    service_name: str = "website-reader-mcp"

    @property
    def allowed_scheme_set(self) -> set[str]:
        return {scheme.strip().lower() for scheme in self.allowed_schemes.split(",") if scheme.strip()}

    @property
    def mcp_allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]

    @property
    def mcp_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.mcp_allowed_origins.split(",") if origin.strip()]

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, value: str) -> str:
        try:
            parse_allowed_domains(value)
        except DomainAllowlistError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @cached_property
    def domain_allowlist(self):
        return parse_allowed_domains(self.allowed_domains)


@lru_cache
def get_settings() -> Settings:
    return Settings()
