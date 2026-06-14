"""Password hashing (PBKDF2-HMAC-SHA256) and JWT encode/decode (HS256)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from core.config import get_settings

_ALGORITHM = "HS256"
_HASH_NAME = "sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password with a random salt; return ``salt$hash`` in hex."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored ``salt$hash`` value."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt, _ITERATIONS)
    return secrets.compare_digest(digest.hex(), hash_hex)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """Create a signed JWT carrying ``sub`` plus ``exp``/``iat``/``iss``/``aud``."""
    settings = get_settings()
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, checking signature, issuer, and audience.

    Raises ``jwt.InvalidTokenError`` (or a subclass) on any failure.
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[_ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )
