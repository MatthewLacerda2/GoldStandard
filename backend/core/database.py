"""Async database engine, session factory, and bootstrap routine.

`init_db()` is the only place outside `repositories/` that issues SQL, and it
does so purely as an application-bootstrap step (extension, table creation,
admin seed). Schema upgrades beyond additive `create_all` should go through
Alembic; this skeleton intentionally ships no migrations.
"""

import inspect
from typing import Any, NamedTuple

import asyncpg
from sqlalchemy import exists, insert, make_url, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from models.base import Base

_ASYNCPG = "postgresql+asyncpg://"

# What SQLAlchemy may hand `asyncpg.connect()` from the URL's query, as keyword
# arguments: asyncpg's own parameters, and the dialect's statement cache size.
_ASYNCPG_KEYS = frozenset(inspect.signature(asyncpg.connect).parameters) | {
    "prepared_statement_cache_size"
}

# libpq's names for what asyncpg takes under another.
_RENAMED = {"sslmode": "ssl", "connect_timeout": "timeout"}

# Any number: advisory locks belong to one database, and this is the only one taken.
_BOOTSTRAP_LOCK = 4_242_001


class DatabaseTarget(NamedTuple):
    """The URL the engine connects with, and the arguments to `asyncpg.connect()`
    a URL cannot carry (a number, a mapping)."""

    url: str
    connect_args: dict[str, Any]


def database_target(url: str) -> DatabaseTarget:
    """Coerce a host's Postgres URL to what the asyncpg driver takes.

    Accepts `postgres://` and `postgresql://` (as emitted by many hosting
    providers) and rewrites them to `postgresql+asyncpg://`. Any other URL,
    one that already names a driver (`postgresql+psycopg://`) included, is
    returned as it is.

    SQLAlchemy hands every query key to `asyncpg.connect()`, and those hosts
    append libpq's: `sslmode` becomes `ssl`, `connect_timeout` becomes
    `timeout`, `application_name` a server setting, and a `channel_binding`
    that only prefers it is dropped. Any other key asyncpg does not take is
    refused here, naming it, rather than failing the first connection.
    """
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            url = _ASYNCPG + url.removeprefix(scheme)
            break
    if not url.startswith(_ASYNCPG):
        return DatabaseTarget(url, {})
    parsed = make_url(url)
    query = dict(parsed.query)
    for libpq, name in _RENAMED.items():
        if libpq in query and name in query:
            # pragma: no mutate start - text nobody parses: the message is read by people
            raise ValueError(f"DATABASE_URL sets both `{libpq}` and `{name}`: keep one")
            # pragma: no mutate end
    connect_args: dict[str, Any] = {}
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")
    if "connect_timeout" in query:
        connect_args["timeout"] = _connect_timeout(query.pop("connect_timeout"))
    if "application_name" in query:
        connect_args["server_settings"] = {"application_name": query.pop("application_name")}
    _drop_channel_binding(query)
    for key in query:
        if key not in _ASYNCPG_KEYS:
            # pragma: no mutate start - text nobody parses: the message is read by people
            raise ValueError(f"DATABASE_URL sets `{key}`, which asyncpg does not take")
            # pragma: no mutate end
    # pragma: no mutate start - equivalent: hide_password=None hides nothing either
    rendered = parsed.set(query=query).render_as_string(hide_password=False)
    # pragma: no mutate end
    return DatabaseTarget(rendered, connect_args)


def normalize_database_url(url: str) -> str:
    """`database_target`'s URL alone: the tests' and tools' engines connect
    without what the app passes beside it."""
    return database_target(url).url


def _connect_timeout(value: str) -> int | None:
    """libpq's whole seconds, where zero or less waits forever (asyncpg's `None`)."""
    try:
        seconds = int(value)
    except ValueError:
        # pragma: no mutate start - text nobody parses: the message is read by people
        raise ValueError(f"DATABASE_URL `connect_timeout={value}` is not whole seconds") from None
        # pragma: no mutate end
    return seconds if seconds > 0 else None


def _drop_channel_binding(query: dict[str, Any]) -> None:
    """asyncpg authenticates without channel binding, which libpq's `prefer`
    (its default) falls back to as well; a URL that requires it is refused
    rather than quietly connecting without it."""
    mode = query.pop("channel_binding", "prefer")
    if mode not in ("prefer", "disable"):
        # pragma: no mutate start - text nobody parses: the message is read by people
        raise ValueError(
            f"DATABASE_URL sets `channel_binding={mode}`, which asyncpg cannot do: "
            "use `channel_binding=prefer`, or drop it (TLS from `sslmode` still applies)"
        )
        # pragma: no mutate end


_settings = get_settings()
_target = database_target(_settings.DATABASE_URL)

engine = create_async_engine(_target.url, future=True, connect_args=_target.connect_args)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Bootstrap the database: pgvector extension, tables, default admin.

    One transaction under one lock: workers or replicas starting together take
    turns, so the first builds an empty database and the rest find it built.
    """
    # Import models so their tables are registered on `Base.metadata`.
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK})
        # pragma: no mutate start - equivalent: SQL reads an unquoted word in any case
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # pragma: no mutate end
        # Additive only. Alembic is the upgrade path for non-additive changes.
        await conn.run_sync(Base.metadata.create_all)
        await _seed_default_admin(conn)


async def _seed_default_admin(conn: AsyncConnection) -> None:
    """Create the default admin user if no user exists yet."""
    from models.user import User
    from utils.security import hash_password

    if await conn.scalar(select(exists().select_from(User))):
        return
    settings = get_settings()
    password_hash = hash_password(settings.DEFAULT_ADMIN_PASSWORD)
    await conn.execute(
        insert(User).values(email=settings.DEFAULT_ADMIN_EMAIL, password_hash=password_hash)
    )
