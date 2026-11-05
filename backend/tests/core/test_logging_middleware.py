"""The access log (``core/logging_middleware.py``): every request but a health
probe leaves one line on ``app.access`` naming its method, path and status (a
crashed one included, as the 500 it answers), and the response, or the crash,
goes through untouched. The line's wording and duration are read by people,
not asserted; only that it formats."""

import logging

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from core.logging_middleware import LoggingMiddleware
from main import app


async def test_a_request_is_logged_once_and_a_health_probe_never(caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        probe = await client.get("/health")
        root = await client.get("/")
    assert probe.json() == {"status": "healthy"}
    assert root.json()["status"] == "ok"
    records = [r for r in caplog.records if r.name == "app.access"]
    assert [r.args[:3] for r in records] == [("GET", "/", 200)]
    records[0].getMessage()  # a line that cannot format is lost to a logging error


async def test_a_request_whose_handler_crashes_is_logged_as_the_500_it_returns(caplog):
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("handler crashed")

    crashing = FastAPI()
    crashing.add_middleware(LoggingMiddleware)
    crashing.include_router(router)

    caplog.set_level(logging.INFO, logger="app.access")
    async with AsyncClient(transport=ASGITransport(app=crashing), base_url="http://test") as client:
        # The crash still reaches Starlette's error handling, which answers 500
        # and re-raises to the server; the access line must not swallow it.
        with pytest.raises(RuntimeError, match="handler crashed"):
            await client.get("/boom")
    records = [r for r in caplog.records if r.name == "app.access"]
    assert [r.args[:3] for r in records] == [("GET", "/boom", 500)]
    records[0].getMessage()
