"""Root test fixtures: per-worktree test DB + rollback-per-test sessions.

The test database name is derived from the repository path so parallel git
worktrees never collide. The database is created on first use (via the
maintenance ``postgres`` database). Each test runs inside an outer transaction
that is rolled back on teardown, so nothing persists between tests.
"""

import hashlib
import os
import subprocess

import asyncpg
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import get_settings
from core.database import normalize_database_url
from models.base import Base

# One-time guard so DDL/database creation happens once per process even though
# the engine fixture is function-scoped (each test runs on its own event loop).
_DB_READY = False


def _repo_root() -> str:
    """Return the worktree root path used to derive the test DB name."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.getcwd()


def _base_url() -> str:
    """Base DATABASE_URL (without the test db name applied).

    Prefers an explicit ``DATABASE_URL`` env var, otherwise falls back to the
    application settings (which load ``.env``).
    """
    raw = os.environ.get("DATABASE_URL") or get_settings().DATABASE_URL
    return normalize_database_url(raw)


def _test_db_name() -> str:
    """Derive a stable per-worktree test database name."""
    digest = hashlib.sha1(_repo_root().encode()).hexdigest()[:12]
    return f"test_gs_{digest}"


def _split_url(url: str) -> tuple[str, str]:
    """Split a SQLAlchemy asyncpg URL into (prefix-up-to-db, current-db)."""
    head, _, tail = url.rpartition("/")
    return head, tail


async def _ensure_database(db_name: str) -> None:
    """Create the test database if it does not already exist."""
    head, _ = _split_url(_base_url())
    # Strip the SQLAlchemy driver marker for a raw asyncpg connection.
    dsn = head.replace("postgresql+asyncpg://", "postgresql://") + "/postgres"
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def engine():
    """Function-scoped engine bound to the per-worktree test database.

    asyncpg connections are bound to the event loop that created them, so the
    engine is created per test (each test runs on its own loop). NullPool avoids
    reusing connections across loops. The database and tables are created once
    per process, guarded by ``_DB_READY``.
    """
    global _DB_READY
    db_name = _test_db_name()
    head, _ = _split_url(_base_url())
    test_engine = create_async_engine(f"{head}/{db_name}", future=True, poolclass=NullPool)
    if not _DB_READY:
        await _ensure_database(db_name)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _DB_READY = True
    yield test_engine
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:
    """Session joined to an outer transaction; rolled back after each test.

    Uses the SQLAlchemy "join an external transaction" recipe: a SAVEPOINT is
    restarted whenever the application code commits, so handler ``commit()``
    calls are isolated and the outer transaction's rollback discards everything.
    """
    connection = await engine.connect()
    transaction = await connection.begin()
    maker = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)
    session = maker()
    await session.begin_nested()

    sync_session = session.sync_session

    @event.listens_for(sync_session, "after_transaction_end")
    def _restart_savepoint(sess, trans) -> None:
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        event.remove(sync_session, "after_transaction_end", _restart_savepoint)
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
