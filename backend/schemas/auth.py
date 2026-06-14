"""Authentication request/response schemas."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Credentials submitted to obtain an access token."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """A minted JWT access token."""

    access_token: str
    token_type: str = "bearer"
