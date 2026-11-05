"""Root test fixtures: per-worktree test DB + rollback-per-test sessions.

The test database name is derived from the repository path so parallel git
worktrees never collide. The database is created on first use (via the
maintenance ``postgres`` database). Each test runs inside an outer transaction
that is rolled back on teardown, so nothing persists between tests.

Under mutation testing (``make back-mutate``) many pytest processes run at
once, so each takes a database of its own, named by its pid when a test first
asks for one and dropped when its session ends (``tools/mutation_db.py``).
"""

import asyncio
import hashlib
import os
import subprocess

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import URL, event, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import get_settings
from core.database import normalize_database_url
from core.rate_limiter import limiter
from models.base import Base
from tools import mutation_db

# mutmut sets this in every process it runs the tests in; the driver sets
# `mutation_db.ENV` beside it.
_UNDER_MUTMUT = "MUTANT_UNDER_TEST"

# The database this process already created, so DDL runs once per process even
# though the engine fixture is function-scoped (each test runs on its own event
# loop). A name rather than a flag, so it never vouches for a database another
# process created (a forked process inherits it).
_READY_DB: str | None = None


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear slowapi's in-process counters before every test.

    The global limit keys on client address, and every test drives the app from
    the same one, so without this a fast suite would trip its own throttle.
    """
    limiter.reset()


def _repo_root() -> str:
    """Return the worktree root path used to derive the test DB name."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return os.getcwd()


def _base_url() -> str:
    """Base DATABASE_URL (without the test db name applied).

    Prefers an explicit ``DATABASE_URL`` env var, otherwise falls back to the
    application settings (which load ``.env``).
    """
    raw = os.environ.get("DATABASE_URL") or get_settings().DATABASE_URL
    return normalize_database_url(raw)


def _worktree_db_name() -> str:
    """Derive a stable per-worktree test database name."""
    digest = hashlib.sha1(_repo_root().encode()).hexdigest()[:12]
    return f"test_gs_{digest}"


def _mutation_base() -> str | None:
    """The driver's base name under mutation testing, else None.

    mutmut run bare (not through ``make back-mutate``) would put every process
    on the worktree's one database, so it fails here, loudly, on the clean run.
    """
    base = os.environ.get(mutation_db.ENV)
    if base is None and _UNDER_MUTMUT in os.environ:
        pytest.fail("mutmut runs through `make back-mutate`, never bare (backend/CLAUDE.md)")
    return base


def _test_db_name() -> str:
    """The worktree's database, or this process' own under mutation testing."""
    base = _mutation_base()
    return mutation_db.process_name(base) if base else _worktree_db_name()


def _test_url(db_name: str) -> URL:
    """The base URL on the test database ``db_name``, every query parameter kept."""
    return make_url(_base_url()).set(database=db_name)


async def _admin_connect() -> asyncpg.Connection:
    """A raw connection to the maintenance ``postgres`` database."""
    return await asyncpg.connect(**mutation_db.admin_connect_args(_base_url()))


async def _ensure_database(db_name: str) -> None:
    """Create the test database if it does not already exist."""
    conn = await _admin_connect()
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _drop_database(name: str) -> None:
    conn = await _admin_connect()
    try:
        await mutation_db.drop(conn, name)
    finally:
        await conn.close()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    """Under mutation testing, drop the database this process created.

    Last of the hooks: pytest tears the last test's fixtures down in its own
    ``pytest_sessionfinish``, and a forced drop before that would cut the
    connection its rollback still needs.
    """
    global _READY_DB
    if os.environ.get(mutation_db.ENV) and _READY_DB == _test_db_name():
        asyncio.run(_drop_database(_READY_DB))
        _READY_DB = None


@pytest_asyncio.fixture
async def engine():
    """Function-scoped engine bound to the per-worktree test database.

    asyncpg connections are bound to the event loop that created them, so the
    engine is created per test (each test runs on its own loop). NullPool avoids
    reusing connections across loops. The database and tables are created once
    per process, guarded by ``_READY_DB``.
    """
    global _READY_DB
    db_name = _test_db_name()
    test_engine = create_async_engine(_test_url(db_name), future=True, poolclass=NullPool)
    if _READY_DB != db_name:
        await _ensure_database(db_name)
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _READY_DB = db_name
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
