"""FastAPI application entrypoint.

Middleware order (outermost first): CORS -> rate limiting -> request logging.
The versioned API router is mounted at ``/api/v1``. The lifespan runs
``init_db()`` once at startup.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.endpoints import api_router
from core.config import get_settings
from core.database import init_db
from core.logging_middleware import LoggingMiddleware
from core.rate_limiter import limiter

APP_NAME = "GoldStandard Backend"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Run database bootstrap on startup."""
    await init_db()
    yield


def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a 429 JSON response when a rate limit is exceeded."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=APP_NAME, lifespan=lifespan)

    # Outermost: CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting (slowapi): register limiter + middleware + handler.
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    # Innermost app-level middleware: request logging (skips /health).
    app.add_middleware(LoggingMiddleware)

    # Versioned API.
    app.include_router(api_router, prefix="/api/v1")

    _register_baseline_routes(app)
    return app


def _register_baseline_routes(app: FastAPI) -> None:
    """Attach the unversioned baseline endpoints."""

    @app.get("/")
    async def root() -> dict[str, str]:
        """Service identity and status."""
        return {"name": APP_NAME, "status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe (intentionally not logged)."""
        return {"status": "healthy"}

    @app.get("/security.txt", response_class=PlainTextResponse)
    async def security_txt() -> str:
        """Plaintext security contact (see securitytxt.org)."""
        return "Contact: mailto:security@example.com\nExpires: 2027-01-01T00:00:00Z\n"


app = create_app()
