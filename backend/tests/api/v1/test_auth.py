"""Auth endpoint tests."""


async def test_login_happy_path(client, user_factory):
    await user_factory(email="login@example.com", password="hunter2!")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "hunter2!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_bad_credentials(client, user_factory):
    await user_factory(email="login@example.com", password="hunter2!")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401
