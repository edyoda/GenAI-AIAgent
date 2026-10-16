"""Logging setup + an MCP middleware that logs every request with caller and duration."""

from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{name}] %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # hide per-request upstream noise
    return logging.getLogger(f"mcp.{name}")


def request_logger(log: logging.Logger):
    """ServerMiddleware: `tools/call get_forecast by demo-agent -> ok (212 ms)`."""

    async def middleware(ctx: Any, call_next: Any) -> Any:
        if ctx.request_id is None:  # notification, nothing interesting to log
            return await call_next(ctx)
        params = ctx.params if isinstance(ctx.params, dict) else {}
        target = params.get("name") or params.get("uri") or ""
        token = get_access_token()
        caller = token.client_id if token else "anonymous"
        start = time.perf_counter()
        try:
            result = await call_next(ctx)
        except Exception as e:
            log.warning("%s %s by %s -> error %s (%.0f ms)", ctx.method, target, caller,
                        type(e).__name__, (time.perf_counter() - start) * 1000)
            raise
        is_error = result.get("isError") if isinstance(result, dict) else getattr(result, "is_error", False)
        status = "tool-error" if is_error else "ok"
        log.info("%s %s by %s -> %s (%.0f ms)", ctx.method, target, caller, status,
                 (time.perf_counter() - start) * 1000)
        return result

    return middleware
