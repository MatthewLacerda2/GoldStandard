"""User endpoint tests."""

import uuid

from repositories import users as users_repo
from utils.security import create_access_token


async def test_list_users_requires_auth(client):
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


async def test_list_users(client, auth_headers):
    resp = await client.get("/api/v1/users", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_user(client, auth_headers):
    resp = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": "new@example.com", "password": "pw12345"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["is_active"] is True
    assert "id" in body


async def test_an_inactive_users_token_is_refused(client, db_session, user_factory):
    user = await user_factory(email="gone@example.com")
    await users_repo.set_active(db_session, user, False)
    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    resp = await client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 401


async def test_a_token_for_a_user_that_does_not_exist_is_refused(client):
    headers = {"Authorization": f"Bearer {create_access_token(subject=str(uuid.uuid4()))}"}
    resp = await client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 401
