"""User data access. The only module that issues user SQL.

Repositories take an ``AsyncSession`` and ``flush()`` (never ``commit()``); the
calling handler owns the transaction boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Return the user with ``user_id`` or ``None``."""
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """Return the user with ``email`` or ``None``."""
    return await session.scalar(select(User).where(User.email == email))


async def list_users(session: AsyncSession) -> list[User]:
    """Return all users ordered by creation time."""
    result = await session.scalars(select(User).order_by(User.created_at))
    return list(result.all())


async def create(session: AsyncSession, email: str, password_hash: str) -> User:
    """Insert a new user and flush so the id is populated."""
    user = User(email=email, password_hash=password_hash, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def set_active(session: AsyncSession, user: User, is_active: bool) -> User:
    """Update the active flag on a user and flush."""
    user.is_active = is_active
    session.add(user)
    await session.flush()
    return user
