"""Password hashing and tokens (``utils/security.py``), on the cases a weak
check would wave through: a malformed stored hash, a token from another
issuer, a token missing a claim. Written from what mutation testing found
unasserted; the happy paths are the API tests'."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from core.config import get_settings
from utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_each_hash_carries_a_fresh_16_byte_salt():
    first, second = hash_password("pw"), hash_password("pw")
    assert first != second
    salt_hex, _, digest_hex = first.partition("$")
    assert len(bytes.fromhex(salt_hex)) == 16 and len(bytes.fromhex(digest_hex)) == 32
    assert verify_password("pw", first) and not verify_password("other", first)


@pytest.mark.parametrize("stored", ["", "no-separator", "not-hex$abcd", None])
def test_a_malformed_stored_hash_is_refused_not_an_error(stored):
    assert verify_password("pw", stored) is False


def test_a_hash_with_a_second_separator_is_refused():
    assert verify_password("pw", f"{hash_password('pw')}$extra") is False


def _token(**claims) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": "someone",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    } | claims
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def test_a_token_the_app_signs_decodes_to_its_subject():
    assert decode_access_token(create_access_token("someone"))["sub"] == "someone"
    assert decode_access_token(_token())["sub"] == "someone"


def test_a_token_from_another_issuer_is_refused():
    with pytest.raises(jwt.InvalidIssuerError):
        decode_access_token(_token(iss="someone-else"))


@pytest.mark.parametrize("claim", ["exp", "iat", "iss", "aud", "sub"])
def test_a_token_missing_a_required_claim_is_refused(claim):
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(_token(**{claim: None}))
