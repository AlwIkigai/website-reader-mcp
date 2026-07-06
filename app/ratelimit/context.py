from contextvars import ContextVar

client_id_ctx: ContextVar[str | None] = ContextVar("client_id", default=None)


def get_client_id() -> str:
    return client_id_ctx.get() or "unknown"
