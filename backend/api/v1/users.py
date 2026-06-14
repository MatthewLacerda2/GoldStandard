"""User management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from repositories import users as users_repo
from schemas.users import UserCreate, UserRead
from utils.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(session: AsyncSession = Depends(get_db)) -> list[UserRead]:
    """Return all users."""
    users = await users_repo.list_users(session)
    return [UserRead.model_validate(u) for u in users]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
) -> UserRead:
    """Create a new user."""
    if await users_repo.get_by_email(session, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = await users_repo.create(session, payload.email, hash_password(payload.password))
    await session.commit()
    return UserRead.model_validate(user)


@router.post("/{user_id}/activate", response_model=UserRead)
async def activate_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> UserRead:
    """Mark a user as active."""
    user = await users_repo.get_by_id(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await users_repo.set_active(session, user, True)
    await session.commit()
    return UserRead.model_validate(user)
