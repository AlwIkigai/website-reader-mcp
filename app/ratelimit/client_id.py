import hashlib

from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    vercel_forwarded = request.headers.get("x-vercel-forwarded-for")
    if vercel_forwarded:
        return vercel_forwarded.split(",")[0].strip()

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client is not None:
        return request.client.host

    return "unknown"


def build_client_id(api_key: str | None, client_ip: str) -> str:
    if api_key:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    else:
        key_hash = "anonymous"

    return f"{key_hash}:{client_ip}"
