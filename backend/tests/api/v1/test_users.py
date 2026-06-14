"""User endpoint tests."""


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
