from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import Settings, get_settings
from app.ratelimit.client_id import build_client_id, get_client_ip
from app.ratelimit.context import client_id_ctx
from app.services.host_allowlist import host_header_matches_allowlist


def extract_api_key(request: Request, settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()

    authorization = request.headers.get("Authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()

    api_key = request.headers.get("X-API-Key")
    if api_key and api_key.strip():
        return api_key.strip()

    return None


def is_valid_api_key(request: Request, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    provided = extract_api_key(request, settings)
    if not provided:
        return False
    return provided == settings.mcp_api_key


def _origin_matches_allowlist(origin: str, allowed_origins: list[str]) -> bool:
    if origin in allowed_origins:
        return True

    for allowed in allowed_origins:
        if allowed.endswith(":*") and origin.startswith(allowed[:-2] + ":"):
            return True

    return False


def is_allowed_mcp_client(request: Request, settings: Settings | None = None) -> bool:
    """Check whether the caller's Host (and optional Origin) may access /mcp."""
    settings = settings or get_settings()
    allowlist = settings.mcp_host_allowlist

    if allowlist.is_restrictive:
        host = request.headers.get("host")
        if not host or not host_header_matches_allowlist(host, allowlist):
            return False

    allowed_origins = settings.mcp_allowed_origin_list
    if allowed_origins:
        origin = request.headers.get("origin")
        if origin and not _origin_matches_allowlist(origin, allowed_origins):
            return False

    return True


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Protect MCP routes with host allowlisting and a static API key."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            if not is_allowed_mcp_client(request):
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})

            if not is_valid_api_key(request):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

            client_id = build_client_id(extract_api_key(request), get_client_ip(request))
            token = client_id_ctx.set(client_id)
            try:
                return await call_next(request)
            finally:
                client_id_ctx.reset(token)

        return await call_next(request)
