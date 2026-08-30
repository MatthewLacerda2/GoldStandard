"""The JWT signing key must meet the RFC 7518 minimum before the app starts."""

import pytest
from pydantic import ValidationError

from core.config import Settings

MIN_SECRET_LENGTH = 32


def test_rejects_jwt_secret_below_the_minimum():
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(JWT_SECRET="too-short-to-sign-with")


def test_accepts_jwt_secret_at_the_boundary():
    secret = "x" * MIN_SECRET_LENGTH
    assert Settings(JWT_SECRET=secret).JWT_SECRET == secret


def test_shipped_default_meets_the_minimum():
    assert len(Settings().JWT_SECRET) >= MIN_SECRET_LENGTH
