"""Item data access. The only module that issues item SQL.

Repositories take an ``AsyncSession`` and ``flush()`` (never ``commit()``); the
calling handler owns the transaction boundary.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.item import Item


async def get_by_id(session: AsyncSession, item_id: uuid.UUID) -> Item | None:
    """Return the item with ``item_id`` or ``None``."""
    return await session.get(Item, item_id)


async def list_items(session: AsyncSession) -> list[Item]:
    """Return all items ordered by creation time."""
    result = await session.scalars(select(Item).order_by(Item.created_at))
    return list(result.all())


async def create(
    session: AsyncSession,
    name: str,
    description: str | None,
    owner_id: uuid.UUID,
) -> Item:
    """Insert a new item and flush so the id is populated."""
    item = Item(name=name, description=description, owner_id=owner_id)
    session.add(item)
    await session.flush()
    return item


async def update(
    session: AsyncSession,
    item: Item,
    name: str | None,
    description: str | None,
) -> Item:
    """Apply partial updates to an item and flush."""
    if name is not None:
        item.name = name
    if description is not None:
        item.description = description
    session.add(item)
    await session.flush()
    # Reload server-managed columns (e.g. updated_at via onupdate) so the
    # object is fully populated for serialization after the caller commits.
    await session.refresh(item)
    return item


async def delete(session: AsyncSession, item: Item) -> None:
    """Delete an item and flush."""
    await session.delete(item)
    await session.flush()
