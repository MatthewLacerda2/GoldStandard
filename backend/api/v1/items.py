"""Item CRUD endpoints (the worked example resource)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from models.item import Item
from models.user import User
from repositories import items as items_repo
from schemas.items import ItemCreate, ItemRead, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


async def _get_or_404(session: AsyncSession, item_id: uuid.UUID) -> Item:
    """Load an item or raise 404."""
    item = await items_repo.get_by_id(session, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.get("", response_model=list[ItemRead])
async def list_items(session: AsyncSession = Depends(get_db)) -> list[ItemRead]:
    """Return all items."""
    items = await items_repo.list_items(session)
    return [ItemRead.model_validate(i) for i in items]


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ItemRead:
    """Return a single item or 404."""
    item = await _get_or_404(session, item_id)
    return ItemRead.model_validate(item)


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ItemCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItemRead:
    """Create an item owned by the current user."""
    item = await items_repo.create(session, payload.name, payload.description, current_user.id)
    await session.commit()
    return ItemRead.model_validate(item)


@router.put("/{item_id}", response_model=ItemRead)
async def update_item(
    item_id: uuid.UUID,
    payload: ItemUpdate,
    session: AsyncSession = Depends(get_db),
) -> ItemRead:
    """Apply partial updates to an item."""
    item = await _get_or_404(session, item_id)
    await items_repo.update(session, item, payload.name, payload.description)
    await session.commit()
    return ItemRead.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete an item."""
    item = await _get_or_404(session, item_id)
    await items_repo.delete(session, item)
    await session.commit()
