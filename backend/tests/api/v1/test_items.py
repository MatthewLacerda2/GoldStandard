"""Item CRUD endpoint tests."""


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
