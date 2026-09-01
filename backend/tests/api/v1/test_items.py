"""Item CRUD endpoint tests."""

import pytest_asyncio

from utils.security import create_access_token


@pytest_asyncio.fixture
async def other_headers(user_factory):
    """Authorization headers for a second user, unrelated to ``auth_headers``."""
    user = await user_factory("other@example.com", "secret456")
    return {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}


async def test_create_and_get_item(client, auth_headers):
    create = await client.post(
        "/api/v1/items",
        headers=auth_headers,
        json={"name": "Widget", "description": "a thing"},
    )
    assert create.status_code == 201
    item_id = create.json()["id"]

    # Persistence: the created item is retrievable.
    got = await client.get(f"/api/v1/items/{item_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["name"] == "Widget"


async def test_update_item(client, auth_headers):
    created = await client.post("/api/v1/items", headers=auth_headers, json={"name": "Old"})
    item_id = created.json()["id"]
    resp = await client.put(f"/api/v1/items/{item_id}", headers=auth_headers, json={"name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


async def test_delete_item(client, auth_headers):
    created = await client.post("/api/v1/items", headers=auth_headers, json={"name": "Temp"})
    item_id = created.json()["id"]
    deleted = await client.delete(f"/api/v1/items/{item_id}", headers=auth_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/items/{item_id}", headers=auth_headers)
    assert missing.status_code == 404


async def test_get_missing_item_404(client, auth_headers):
    fake = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"/api/v1/items/{fake}", headers=auth_headers)
    assert resp.status_code == 404


async def test_another_users_item_is_404_everywhere(client, auth_headers, other_headers):
    created = await client.post("/api/v1/items", headers=auth_headers, json={"name": "Private"})
    item_id = created.json()["id"]

    # 404 rather than 403: the endpoint must not confirm the id exists.
    read = await client.get(f"/api/v1/items/{item_id}", headers=other_headers)
    assert read.status_code == 404
    write = await client.put(
        f"/api/v1/items/{item_id}", headers=other_headers, json={"name": "Stolen"}
    )
    assert write.status_code == 404
    removed = await client.delete(f"/api/v1/items/{item_id}", headers=other_headers)
    assert removed.status_code == 404

    # The owner's item survived every attempt untouched.
    owner_view = await client.get(f"/api/v1/items/{item_id}", headers=auth_headers)
    assert owner_view.status_code == 200
    assert owner_view.json()["name"] == "Private"


async def test_list_items_returns_only_the_callers_items(client, auth_headers, other_headers):
    await client.post("/api/v1/items", headers=auth_headers, json={"name": "Mine"})
    await client.post("/api/v1/items", headers=other_headers, json={"name": "Theirs"})

    mine = await client.get("/api/v1/items", headers=auth_headers)
    assert mine.status_code == 200
    assert [i["name"] for i in mine.json()] == ["Mine"]

    theirs = await client.get("/api/v1/items", headers=other_headers)
    assert [i["name"] for i in theirs.json()] == ["Theirs"]


async def test_explicit_null_clears_description(client, auth_headers):
    created = await client.post(
        "/api/v1/items", headers=auth_headers, json={"name": "Note", "description": "draft"}
    )
    item_id = created.json()["id"]

    cleared = await client.put(
        f"/api/v1/items/{item_id}", headers=auth_headers, json={"description": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None
    assert cleared.json()["name"] == "Note"

    # The NULL was written, not just reflected back in the response.
    reread = await client.get(f"/api/v1/items/{item_id}", headers=auth_headers)
    assert reread.json()["description"] is None


async def test_omitted_description_is_left_unchanged(client, auth_headers):
    created = await client.post(
        "/api/v1/items", headers=auth_headers, json={"name": "Note", "description": "keep me"}
    )
    item_id = created.json()["id"]

    renamed = await client.put(
        f"/api/v1/items/{item_id}", headers=auth_headers, json={"name": "Renamed"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"
    assert renamed.json()["description"] == "keep me"


async def test_explicit_null_name_is_rejected(client, auth_headers):
    created = await client.post("/api/v1/items", headers=auth_headers, json={"name": "Keeps name"})
    item_id = created.json()["id"]

    resp = await client.put(f"/api/v1/items/{item_id}", headers=auth_headers, json={"name": None})
    assert resp.status_code == 422
