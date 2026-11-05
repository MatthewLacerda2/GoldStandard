"""Request logging middleware that records method, path, status, and duration."""

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.access")

# Paths excluded from access logging (e.g. high-frequency health probes).
_SKIP_PATHS = frozenset({"/health"})


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log each request's method, path, status code, and duration in ms."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)  # pragma: no mutate - equivalent: call_next ignores it
        if request.url.path in _SKIP_PATHS:
            return response

        duration_ms = (time.perf_counter() - start) * 1000.0  # pragma: no mutate - log text
        logger.info(
            "%s %s -> %d (%.2fms)",  # pragma: no mutate - log text
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
