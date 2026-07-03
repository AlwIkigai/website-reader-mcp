from functools import cached_property, lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.host_allowlist import HostAllowlistError, parse_mcp_allowed_hosts


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
    mcp_allowed_hosts: str = Field(default="", alias="MCP_ALLOWED_HOSTS")
    mcp_allowed_origins: str = Field(default="", alias="MCP_ALLOWED_ORIGINS")

    user_agent: str = "WebsiteReaderMCP/0.1"
    max_redirects: int = 5
    service_name: str = "website-reader-mcp"

    @property
    def allowed_scheme_set(self) -> set[str]:
        return {scheme.strip().lower() for scheme in self.allowed_schemes.split(",") if scheme.strip()}

    @property
    def mcp_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.mcp_allowed_origins.split(",") if origin.strip()]

    @field_validator("mcp_allowed_hosts")
    @classmethod
    def validate_mcp_allowed_hosts(cls, value: str) -> str:
        try:
            parse_mcp_allowed_hosts(value)
        except HostAllowlistError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @cached_property
    def mcp_host_allowlist(self):
        return parse_mcp_allowed_hosts(self.mcp_allowed_hosts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
