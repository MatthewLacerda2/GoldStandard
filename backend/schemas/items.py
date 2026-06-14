"""Item request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemCreate(BaseModel):
    """Payload to create an item."""

    name: str
    description: str | None = None


class ItemUpdate(BaseModel):
    """Payload to update an item; all fields optional."""

    name: str | None = None
    description: str | None = None


class ItemRead(BaseModel):
    """Item representation returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
