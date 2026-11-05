"""The access log (``core/logging_middleware.py``): every request leaves one
line on ``app.access`` except a health probe, and the response goes through
untouched. What the line says is read by people, not asserted."""

import logging

from httpx import ASGITransport, AsyncClient

from main import app


async def test_a_request_is_logged_once_and_a_health_probe_never(caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        probe = await client.get("/health")
        root = await client.get("/")
    assert probe.json() == {"status": "healthy"}
    assert root.json()["status"] == "ok"
    lines = [r.getMessage() for r in caplog.records if r.name == "app.access"]
    assert len(lines) == 1 and lines[0].startswith("GET / ")
