"""The global rate limit throttles every route, database or not.

The limiter runs in middleware, ahead of routing, so these tests drive the
unauthenticated `/health` route straight through the ASGI transport: no
`db_session`, no `client` fixture, no Postgres. slowapi counts requests
in-process keyed by client address; the root `reset_rate_limiter` fixture
clears those counters before each test, so a burst here starts from zero.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.config import Settings
from core.rate_limiter import default_limits
from main import app

REQUESTS_PER_SECOND = 10


@pytest_asyncio.fixture
async def throttled_client():
    """Client bound to the app, driving it over ASGI without a database."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def test_shipped_default_is_ten_requests_per_second():
    assert Settings.model_fields["RATE_LIMIT_DEFAULT"].default == f"{REQUESTS_PER_SECOND}/second"


def test_an_empty_setting_leaves_the_limiter_with_nothing_to_enforce():
    assert default_limits("") == []
    assert default_limits("   ") == []
    assert default_limits("10/second") == ["10/second"]


async def test_requests_up_to_the_limit_are_served(throttled_client):
    for _ in range(REQUESTS_PER_SECOND):
        assert (await throttled_client.get("/health")).status_code == 200


async def test_a_burst_past_the_limit_is_rejected_with_429(throttled_client):
    for _ in range(REQUESTS_PER_SECOND):
        await throttled_client.get("/health")

    response = await throttled_client.get("/health")

    assert response.status_code == 429
    assert response.json() == {"detail": f"Rate limit exceeded: {REQUESTS_PER_SECOND} per 1 second"}
