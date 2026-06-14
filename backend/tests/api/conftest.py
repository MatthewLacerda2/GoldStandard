"""Shared API-test fixtures: HTTP client, auth headers, factories.

These live up the tree so individual test files never redefine them. The app's
``get_db`` dependency is overridden to hand out the rollback-scoped test
session, so requests share the same transaction the test inspects.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.deps import get_db
from main import app
from repositories import users as users_repo
from utils.security import create_access_token, hash_password


@pytest_asyncio.fixture
async def client(db_session):
    """HTTPX client bound to the app with get_db overridden to the test session."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user_factory(db_session):
    """Return a coroutine that creates an active user with a known password."""

    async def _make(email: str = "user@example.com", password: str = "secret123"):
        user = await users_repo.create(db_session, email, hash_password(password))
        await db_session.commit()
        return user

    return _make


@pytest_asyncio.fixture
async def auth_headers(user_factory):
    """Create a user and return Authorization headers carrying its token."""
    user = await user_factory()
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}
