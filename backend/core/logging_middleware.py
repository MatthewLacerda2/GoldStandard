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
        try:
            response = await call_next(request)  # pragma: no mutate - equivalent: arg is ignored
        except Exception:
            # The handler raised, and call_next re-raises it. Starlette's
            # outermost error handler answers it with a 500, the status the
            # client sees: record that, and let the exception go on to it.
            _log_access(request, start, 500)
            raise
        _log_access(request, start, response.status_code)
        return response


def _log_access(request: Request, start: float, status: int) -> None:
    """Write the request's access line, unless its path is never logged."""
    if request.url.path in _SKIP_PATHS:
        return
    duration_ms = (time.perf_counter() - start) * 1000.0  # pragma: no mutate - log text
    logger.info(
        "%s %s -> %d (%.2fms)",  # pragma: no mutate - log text
        request.method,
        request.url.path,
        status,
        duration_ms,
    )
