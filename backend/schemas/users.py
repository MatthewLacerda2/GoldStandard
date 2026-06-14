"""User request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    """Payload to create a user."""

    email: str
    password: str


class UserRead(BaseModel):
    """User representation returned to clients (no secrets)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
