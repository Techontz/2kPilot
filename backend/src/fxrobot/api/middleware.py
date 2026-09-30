"""Correlation IDs, request logging and security headers."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from fxrobot.core.context import sanitize_correlation_id, set_correlation_id

logger = logging.getLogger("fxrobot.http")

CORRELATION_HEADER = "X-Request-ID"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # financial data must not be cached by intermediaries
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_and_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cid = sanitize_correlation_id(request.headers.get(CORRELATION_HEADER))
        set_correlation_id(cid)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers[CORRELATION_HEADER] = cid
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if not request.url.path.startswith("/api/v1/health"):
            logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={"status": response.status_code, "duration_ms": duration_ms},
            )
        return response
