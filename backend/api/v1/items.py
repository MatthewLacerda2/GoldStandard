"""Item CRUD endpoints (the worked example resource).

Every handler is scoped to the authenticated caller: an item belongs to the
user who created it, and no other user can see or touch it. The router-level
dependency in ``api/endpoints.py`` only authenticates — it does not hand the
handler a user — so each handler declares ``get_current_user`` for itself.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from models.item import Item
from models.user import User
from repositories import items as items_repo
from schemas.items import ItemCreate, ItemRead, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


async def _get_owned_or_404(session: AsyncSession, item_id: uuid.UUID, owner: User) -> Item:
    """Load an item owned by ``owner`` or raise 404.

    Another user's item answers 404 rather than 403 on purpose: a 403 would
    confirm that the id exists.
    """
    item = await items_repo.get_owned(session, item_id, owner.id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.get("", response_model=list[ItemRead])
async def list_items(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ItemRead]:
    """Return the current user's items."""
    items = await items_repo.list_owned(session, current_user.id)
    return [ItemRead.model_validate(i) for i in items]


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ItemRead:
    """Return one of the current user's items, or 404."""
    item = await _get_owned_or_404(session, item_id, current_user)
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
    current_user: User = Depends(get_current_user),
) -> ItemRead:
    """Apply the fields the client sent to one of the current user's items."""
    item = await _get_owned_or_404(session, item_id, current_user)
    await items_repo.update(session, item, payload.model_dump(exclude_unset=True))
    await session.commit()
    return ItemRead.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete one of the current user's items."""
    item = await _get_owned_or_404(session, item_id, current_user)
    await items_repo.delete(session, item)
    await session.commit()
