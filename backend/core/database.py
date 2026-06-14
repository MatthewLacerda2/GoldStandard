"""Async database engine, session factory, and bootstrap routine.

`init_db()` is the only place outside `repositories/` that issues SQL, and it
does so purely as an application-bootstrap step (extension, table creation,
admin seed). Schema upgrades beyond additive `create_all` should go through
Alembic; this skeleton intentionally ships no migrations.
"""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from models.base import Base


def normalize_database_url(url: str) -> str:
    """Coerce a plain Postgres URL to the asyncpg driver form.

    Accepts `postgres://` and `postgresql://` (as emitted by many hosting
    providers) and rewrites them to `postgresql+asyncpg://`. URLs that already
    specify a driver are returned unchanged.
    """
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


_settings = get_settings()
DATABASE_URL = normalize_database_url(_settings.DATABASE_URL)

engine = create_async_engine(DATABASE_URL, future=True)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Bootstrap the database: pgvector extension, tables, default admin."""
    # Import models so their tables are registered on `Base.metadata`.
    import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Additive only. Alembic is the upgrade path for non-additive changes.
        await conn.run_sync(Base.metadata.create_all)

    await _seed_default_admin()


async def _seed_default_admin() -> None:
    """Create the default admin user if no user exists yet."""
    from models.user import User
    from utils.security import hash_password

    settings = get_settings()
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).limit(1))
        if existing is not None:
            return
        admin = User(
            email=settings.DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
            is_active=True,
        )
        session.add(admin)
        await session.commit()
