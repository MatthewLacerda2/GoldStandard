"""Bootstrap (``core/database.py``): the URL a host hands over is coerced to the
async driver, and ``init_db`` builds an empty database into a working one
(extension, tables, an admin who can log in) without touching one that already
has users. ``init_db`` runs its DDL inside the test's transaction, so the
rollback undoes it like any other write."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, make_url, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import database
from core.config import get_settings
from models.base import Base
from models.user import User
from utils.security import hash_password, verify_password

ASYNC = "postgresql+asyncpg://u:p@db:5432/app"


@pytest.mark.parametrize(
    "url",
    ["postgresql://u:p@db:5432/app", "postgres://u:p@db:5432/app", ASYNC],
)
def test_a_postgres_url_ends_on_the_async_driver(url):
    assert database.normalize_database_url(url) == ASYNC


def test_a_neon_url_reaches_asyncpg_under_its_names():
    """Neon's default URL: libpq's keys, none of which ``asyncpg.connect()`` takes."""
    url = "postgresql://u:p@ep-x.neon.tech/app?sslmode=require&channel_binding=prefer"
    target = database.database_target(f"{url}&connect_timeout=10&application_name=web")
    result = make_url(target.url)
    assert result.drivername == "postgresql+asyncpg" and result.password == "p"
    assert dict(result.query) == {"ssl": "require"}
    assert target.connect_args == {"timeout": 10, "server_settings": {"application_name": "web"}}


@pytest.mark.parametrize("seconds, timeout", [("1", 1), ("0", None), ("-5", None)])
def test_connect_timeout_keeps_libpqs_meaning(seconds, timeout):
    """Zero or less waits forever in libpq; asyncpg's ``timeout=0`` would never wait."""
    target = database.database_target(f"postgres://u:p@db/app?connect_timeout={seconds}")
    assert target.connect_args == {"timeout": timeout}


def test_a_connect_timeout_that_is_not_seconds_is_refused():
    with pytest.raises(ValueError, match="`connect_timeout=soon`"):
        database.normalize_database_url("postgres://u:p@db/app?connect_timeout=soon")


def test_channel_binding_off_or_preferred_is_dropped():
    """asyncpg cannot bind the channel, and libpq's ``prefer`` falls back the same way."""
    for mode in ("prefer", "disable"):
        url = database.normalize_database_url(f"postgres://u:p@db/app?channel_binding={mode}")
        assert url == ASYNC.replace(":5432", "")


@pytest.mark.parametrize("mode", ["require", "always"])
def test_channel_binding_required_is_refused(mode):
    """Dropping it would quietly connect without the protection the URL asked for."""
    with pytest.raises(ValueError, match=f"`channel_binding={mode}`"):
        database.normalize_database_url(f"postgres://u:p@db/app?channel_binding={mode}")


@pytest.mark.parametrize("key", ["sslrootcert", "keepalives", "options"])
def test_a_key_asyncpg_does_not_take_is_refused_by_name(key):
    """At startup, not as a ``TypeError`` on the first connection."""
    with pytest.raises(ValueError, match=f"`{key}`"):
        database.normalize_database_url(f"postgres://u:p@db/app?ssl=require&{key}=x")


def test_keys_asyncpg_takes_pass_through():
    query = {"target_session_attrs": "any", "command_timeout": "9", "ssl": "require"}
    url = make_url(ASYNC).set(query={**query, "prepared_statement_cache_size": "0"})
    target = database.database_target(url.render_as_string(hide_password=False))
    assert make_url(target.url) == url and target.connect_args == {}


@pytest.mark.parametrize(
    "query, keys",
    [
        ("sslmode=require&ssl=disable", "`sslmode` and `ssl`"),
        ("ssl=disable&sslmode=require", "`sslmode` and `ssl`"),
        ("connect_timeout=5&timeout=9", "`connect_timeout` and `timeout`"),
    ],
)
def test_a_url_setting_a_key_under_both_names_is_refused(query, keys):
    """Either one winning silently could connect without TLS, or wait the wrong time."""
    with pytest.raises(ValueError, match=f"both {keys}"):
        database.normalize_database_url(f"postgres://u:p@db/app?{query}")


@pytest.mark.parametrize(
    "url", ["postgresql+psycopg://u:p@db/app?sslmode=require", "sqlite:///x.db"]
)
def test_a_url_naming_another_driver_is_left_alone(url):
    """Its driver takes libpq's names, and arguments meant for asyncpg would break it."""
    assert database.database_target(url) == (url, {})


async def test_a_neon_style_url_connects(engine):
    """What the host adds reaches the server, not ``asyncpg.connect()`` as a ``TypeError``."""
    query = {"sslmode": "disable", "channel_binding": "prefer", "connect_timeout": "10"}
    raw = engine.url.set(drivername="postgresql", query={**query, "application_name": "gs"})
    url, connect_args = database.database_target(raw.render_as_string(hide_password=False))
    neon = create_async_engine(url, connect_args=connect_args, poolclass=NullPool)
    try:
        async with neon.connect() as conn:
            assert await conn.scalar(text("SHOW application_name")) == "gs"
    finally:
        await neon.dispose()


@asynccontextmanager
async def _lend(value):
    """``async with`` over ``value`` that leaves it open: the fixture owns it."""
    yield value


@pytest.fixture
async def bootstrap(db_session, monkeypatch):
    """The test's connection in place of the app's engine."""
    conn = await db_session.connection()
    monkeypatch.setattr(database, "engine", SimpleNamespace(begin=lambda: _lend(conn)))
    return conn


async def _has_vector(conn) -> bool:
    found = await conn.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    return found is not None


async def test_init_db_builds_an_empty_database(bootstrap, db_session):
    await bootstrap.run_sync(Base.metadata.drop_all)
    await bootstrap.execute(text("DROP EXTENSION IF EXISTS vector"))
    assert not await _has_vector(bootstrap)
    await database.init_db()
    assert await _has_vector(bootstrap)
    tables = await bootstrap.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert tables >= set(Base.metadata.tables)
    settings = get_settings()
    admin = await db_session.scalar(select(User))
    assert admin.email == settings.DEFAULT_ADMIN_EMAIL and admin.is_active
    assert verify_password(settings.DEFAULT_ADMIN_PASSWORD, admin.password_hash)


async def test_no_admin_is_seeded_once_a_user_exists(bootstrap, db_session):
    db_session.add(User(email="someone@example.com", password_hash=hash_password("pw")))
    await db_session.commit()
    await database.init_db()
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def _drop_and_create(engine, name: str, *, create: bool) -> None:
    async with engine.connect() as conn:
        autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        if create:
            await autocommit.execute(text(f'CREATE DATABASE "{name}"'))


@pytest.fixture
async def empty_database(engine, monkeypatch):
    """A database of its own, empty, named after the test's and dropped after.

    Concurrent bootstraps need connections of their own, and those commit: the
    rollback that undoes every other test's writes cannot undo theirs. Both the
    engine and the session factory point at it, so no bootstrap reaches another.
    """
    name = f"{engine.url.database}_bootstrap"
    await _drop_and_create(engine, name, create=True)
    scratch = create_async_engine(engine.url.set(database=name), poolclass=NullPool)
    monkeypatch.setattr(database, "engine", scratch)
    monkeypatch.setattr(database, "SessionLocal", async_sessionmaker(scratch))
    try:
        yield scratch
    finally:
        await scratch.dispose()
        await _drop_and_create(engine, name, create=False)


async def test_workers_starting_together_seed_one_admin(empty_database):
    """Every worker or replica bootstraps at startup; none may crash on the others."""
    await asyncio.gather(*(database.init_db() for _ in range(3)))
    async with empty_database.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(User)) == 1
