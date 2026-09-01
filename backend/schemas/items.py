"""Item request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class ItemCreate(BaseModel):
    """Payload to create an item."""

    name: str
    description: str | None = None


class ItemUpdate(BaseModel):
    """Partial update: only the keys present in the body are written.

    A key set to ``null`` clears that column; an omitted key leaves it
    unchanged. ``name`` is optional to send but never nullable — the column is
    ``NOT NULL`` — so an explicit ``null`` there is rejected as a 422 rather
    than reaching the database.
    """

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _reject_null_name(cls, value: str | None) -> str | None:
        """Run only when ``name`` is present, so omitting it stays legal."""
        if value is None:
            raise ValueError("name cannot be null; omit the key to leave it unchanged")
        return value


class ItemRead(BaseModel):
    """Item representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
