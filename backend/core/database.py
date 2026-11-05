"""Async database engine, session factory, and bootstrap routine.

`init_db()` is the only place outside `repositories/` that issues SQL, and it
does so purely as an application-bootstrap step (extension, table creation,
admin seed). Schema upgrades beyond additive `create_all` should go through
Alembic; this skeleton intentionally ships no migrations.
"""

import math
from collections.abc import Callable
from typing import Any, NamedTuple

from sqlalchemy import URL, exists, func, insert, make_url, select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from models.base import Base

_ASYNCPG = "postgresql+asyncpg://"

# SQLAlchemy hands every query value to `asyncpg.connect()` as text. These keys
# work that way: asyncpg wants text, or SQLAlchemy (`port`, the dialect's
# `prepared_statement_cache_size`) or asyncpg (`command_timeout`) converts it.
_TEXT_KEYS = frozenset(
    {"host", "port", "user", "password", "database", "passfile", "service", "servicefile"}
    | {"ssl", "target_session_attrs", "krbsrvname", "gsslib"}
    | {"command_timeout", "prepared_statement_cache_size"}
)


def _seconds(value: str) -> float:
    """asyncpg's `timeout`: a finite number of seconds, more than none."""
    seconds = float(value)
    if not (math.isfinite(seconds) and seconds > 0):
        raise ValueError  # `_number` names the key
    return seconds


def _count(value: str) -> int:
    """A cache size or lifetime, where 0 turns it off."""
    count = int(value)
    if count < 0:
        raise ValueError  # `_number` names the key
    return count


def _libpq_seconds(value: str) -> int | None:
    """libpq's `connect_timeout`: whole seconds, where zero or less waits forever
    (asyncpg's `None`)."""
    seconds = int(value)
    return seconds if seconds > 0 else None


# asyncpg's parameters that take a number nobody converts: converted here, and
# passed beside the URL. `statement_cache_size=0` turns asyncpg's statement
# cache off; behind a pooler in transaction mode SQLAlchemy also needs
# `prepared_statement_cache_size=0` (a URL key that passes through) and a
# `prepared_statement_name_func`, which no URL can carry.
_NUMBER_KEYS: dict[str, Callable[[str], Any]] = {
    "timeout": _seconds,
    "statement_cache_size": _count,
    "max_cached_statement_lifetime": _count,
    "max_cacheable_statement_size": _count,
}

# libpq's names for what asyncpg takes under another, and what its value becomes:
# text that stays in the URL (no converter), or a value converted to what libpq
# means by it and passed beside the URL.
_RENAMED: dict[str, tuple[str, Callable[[str], Any] | None]] = {
    "sslmode": ("ssl", None),
    "connect_timeout": ("timeout", _libpq_seconds),
}

# Keys a URL may repeat: asyncpg's multi-host form, `?host=a:5432&host=b:5432`.
_REPEATABLE = frozenset({"host", "port"})

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

    SQLAlchemy hands every query key to `asyncpg.connect()` as a keyword
    argument, in text, and those hosts append libpq's: `sslmode` becomes `ssl`,
    `connect_timeout` becomes `timeout`, `application_name` a server setting,
    and a `channel_binding` that only prefers it is dropped. asyncpg's own
    numeric keys are converted. A key set twice (but for the multi-host
    `host` and `port`), a number out of range and any other key are refused
    here, naming the key, rather than failing the first connection.
    """
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            url = _ASYNCPG + url.removeprefix(scheme)
            break
    if not url.startswith(_ASYNCPG):
        return DatabaseTarget(url, {})
    parsed = make_url(url)
    query = dict(parsed.query)
    for key, value in query.items():
        if isinstance(value, tuple) and key not in _REPEATABLE:
            # pragma: no mutate start - text nobody parses: the message is read by people
            raise ValueError(f"DATABASE_URL sets `{key}` more than once: keep one")
            # pragma: no mutate end
    connect_args: dict[str, Any] = {}
    for libpq, (name, convert) in _RENAMED.items():
        if libpq not in query:
            continue
        if name in query:
            # pragma: no mutate start - text nobody parses: the message is read by people
            raise ValueError(f"DATABASE_URL sets both `{libpq}` and `{name}`: keep one")
            # pragma: no mutate end
        value = query.pop(libpq)
        if convert is None:
            query[name] = value
        else:
            connect_args[name] = _number(libpq, value, convert)
    for key, convert in _NUMBER_KEYS.items():
        if key in query:
            connect_args[key] = _number(key, query.pop(key), convert)
    if "application_name" in query:
        connect_args["server_settings"] = {"application_name": query.pop("application_name")}
    _drop_channel_binding(query)
    for key in query:
        if key not in _TEXT_KEYS:
            # pragma: no mutate start - text nobody parses: the message is read by people
            raise ValueError(f"DATABASE_URL sets `{key}`, which asyncpg does not take from a URL")
            # pragma: no mutate end
    return DatabaseTarget(_with_password(parsed.set(query=query)), connect_args)


def normalize_database_url(url: str) -> str:
    """`database_target`'s URL alone: the tests' and tools' engines connect
    without what the app passes beside it."""
    return database_target(url).url


def _with_password(url: URL) -> str:
    """The URL as text, password included, which `str(url)` would mask."""
    return url.render_as_string(  # pragma: no mutate - equivalent: hide_password=None hides nothing either
        hide_password=False,
    )


def _number(key: str, value: str, convert: Callable[[str], Any]) -> Any:
    """`convert(value)`, or an error naming the key when the value is not one it takes."""
    try:
        return convert(value)
    except ValueError:
        # pragma: no mutate start - text nobody parses: the message is read by people
        raise ValueError(f"DATABASE_URL `{key}={value}` is not a number it takes") from None
        # pragma: no mutate end


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
        await conn.execute(select(func.pg_advisory_xact_lock(_BOOTSTRAP_LOCK)))
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
