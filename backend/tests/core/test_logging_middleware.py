"""The access log (``core/logging_middleware.py``): every request but a health
probe leaves one line on ``app.access`` naming its method, path and status,
and the response goes through untouched. The line's wording and duration are
read by people, not asserted; only that it formats."""

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
    records = [r for r in caplog.records if r.name == "app.access"]
    assert [r.args[:3] for r in records] == [("GET", "/", 200)]
    records[0].getMessage()  # a line that cannot format is lost to a logging error
