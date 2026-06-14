"""Shared FastAPI dependencies: database session and current user."""

import uuid
from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal
from models.user import User
from repositories import users as users_repo
from utils.security import decode_access_token

# auto_error=False so a missing token raises OUR 401 below, not the default 403.
_bearer = HTTPBearer(auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield one AsyncSession per request and close it afterwards.

    The session is not committed here; handlers own the transaction boundary.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Validate the bearer token and return the active user it identifies."""
    if credentials is None:
        raise _CREDENTIALS_EXCEPTION
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await users_repo.get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION
    return user
