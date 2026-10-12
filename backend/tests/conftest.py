"""Root test fixtures: per-worktree test DB + rollback-per-test sessions.

The test database name is derived from the repository path so parallel git
worktrees never collide. The database is created on first use (via the
maintenance ``postgres`` database). Each test runs inside an outer transaction
that is rolled back on teardown, so nothing persists between tests.

Under mutation testing (``make back-mutate``) many pytest processes run at
once, and on one shared database their uncommitted rows (the same user email,
say) block each other until mutants time out, and a timeout counts as killed.
So each of those processes gets a database of its own, dropped when its session
ends; ``drop_mutation_databases`` sweeps the ones a killed process left behind.
"""

import asyncio
import hashlib
import os
import subprocess

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import get_settings
from core.database import normalize_database_url
from core.rate_limiter import limiter
from models.base import Base

# mutmut sets this in every process it runs the tests in.
_MUTATION_ENV = "MUTANT_UNDER_TEST"

# The database this process already created, so DDL runs once per process even
# though the engine fixture is function-scoped (each test runs on its own event
# loop). A name rather than a flag: a process mutmut forks inherits it, and
# must still create its own.
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
    except (subprocess.CalledProcessError, FileNotFoundError):
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


def _mutation_prefix() -> str:
    return f"{_worktree_db_name()}_mut_"


def _test_db_name() -> str:
    """The worktree's database, or this process' own under mutation testing."""
    if _MUTATION_ENV in os.environ:
        return f"{_mutation_prefix()}{os.getpid()}"
    return _worktree_db_name()


def _split_url(url: str) -> tuple[str, str]:
    """Split a SQLAlchemy asyncpg URL into (prefix-up-to-db, current-db)."""
    head, _, tail = url.rpartition("/")
    return head, tail


async def _admin_connect() -> asyncpg.Connection:
    """A raw connection to the maintenance ``postgres`` database."""
    head, _ = _split_url(_base_url())
    # Strip the SQLAlchemy driver marker for a raw asyncpg connection.
    return await asyncpg.connect(
        head.replace("postgresql+asyncpg://", "postgresql://") + "/postgres"
    )


async def _ensure_database(db_name: str) -> None:
    """Create the test database if it does not already exist."""
    conn = await _admin_connect()
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _drop_databases(names: list[str]) -> list[str]:
    conn = await _admin_connect()
    try:
        for name in names:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()
    return names


async def drop_mutation_databases() -> list[str]:
    """Drop every mutation database of this worktree; return their names."""
    conn = await _admin_connect()
    try:
        rows = await conn.fetch(
            "SELECT datname FROM pg_database WHERE starts_with(datname, $1)", _mutation_prefix()
        )
    finally:
        await conn.close()
    return await _drop_databases([row["datname"] for row in rows])


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Under mutation testing, drop the database this process created.

    mutmut runs several sessions in its own process (mapping tests, the clean
    run), so the next one must find the database gone and create it again.
    """
    global _READY_DB
    if _MUTATION_ENV in os.environ and _READY_DB == _test_db_name():
        asyncio.run(_drop_databases([_READY_DB]))
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
    head, _ = _split_url(_base_url())
    test_engine = create_async_engine(f"{head}/{db_name}", future=True, poolclass=NullPool)
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
