"""``get_db``, the one dependency every API test overrides: it hands out a
session of the app's own factory. Creating one opens no connection, so this
needs no database."""

from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db


async def test_get_db_yields_one_session_per_request():
    sessions = [session async for session in get_db()]
    assert len(sessions) == 1 and isinstance(sessions[0], AsyncSession)
