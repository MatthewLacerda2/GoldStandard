"""Bootstrap (``core/database.py``): the URL a host hands over is coerced to the
async driver, and ``init_db`` builds an empty database into a working one
(extension, tables, an admin who can log in) without touching one that already
has users. ``init_db`` runs its DDL inside the test's transaction, so the
rollback undoes it like any other write."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, make_url, select, text

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


def test_a_hosts_sslmode_reaches_asyncpg_under_its_name():
    """A host's URL often ends in libpq's ``sslmode``; asyncpg refuses the key."""
    url = "postgres://u:p@db:5432/app?sslmode=require&application_name=web"
    result = make_url(database.normalize_database_url(url))
    assert result.drivername == "postgresql+asyncpg" and result.password == "p"
    assert dict(result.query) == {"ssl": "require", "application_name": "web"}


@pytest.mark.parametrize(
    "url", ["postgresql+psycopg://u:p@db/app?sslmode=require", "sqlite:///x.db"]
)
def test_a_url_naming_another_driver_is_left_alone(url):
    assert database.normalize_database_url(url) == url


@asynccontextmanager
async def _lend(value):
    """``async with`` over ``value`` that leaves it open: the fixture owns it."""
    yield value


@pytest.fixture
async def bootstrap(db_session, monkeypatch):
    """The test's connection and session in place of the app's engine and factory."""
    conn = await db_session.connection()
    monkeypatch.setattr(database, "engine", SimpleNamespace(begin=lambda: _lend(conn)))
    monkeypatch.setattr(database, "SessionLocal", lambda: _lend(db_session))
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
