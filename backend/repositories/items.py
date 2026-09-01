"""Item data access. The only module that issues item SQL.

Repositories take an ``AsyncSession`` and ``flush()`` (never ``commit()``); the
calling handler owns the transaction boundary. Reads are scoped to an owner, so
ownership is enforced in SQL rather than re-checked by every caller.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.item import Item


async def get_owned(
    session: AsyncSession,
    item_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> Item | None:
    """Return the item with ``item_id`` if ``owner_id`` owns it, else ``None``."""
    return await session.scalar(select(Item).where(Item.id == item_id, Item.owner_id == owner_id))


async def list_owned(session: AsyncSession, owner_id: uuid.UUID) -> list[Item]:
    """Return the items owned by ``owner_id``, ordered by creation time."""
    result = await session.scalars(
        select(Item).where(Item.owner_id == owner_id).order_by(Item.created_at)
    )
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


async def update(session: AsyncSession, item: Item, fields: Mapping[str, Any]) -> Item:
    """Write the fields a client actually sent onto an item, and flush.

    ``fields`` holds only the keys present in the request body (Pydantic's
    ``exclude_unset``), which is what separates "clear this column" — an
    explicit ``null`` — from "leave it alone" — an omitted key.
    """
    for column, value in fields.items():
        setattr(item, column, value)
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
