import uuid

import pytest


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


async def _signup(client) -> str:
    resp = await client.post("/v1/auth/signup", json={"email": _email(), "password": "password123"})
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_key_requires_auth(client):
    resp = await client.post("/v1/keys", json={"name": "no auth"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_key_returns_raw_key_once(client):
    token = await _signup(client)
    resp = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "first key"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"].startswith("sk_live_")
    assert body["key_prefix"] == body["key"][:12]
    assert body["revoked"] is False


@pytest.mark.asyncio
async def test_list_keys_only_returns_own_keys(client):
    token_a = await _signup(client)
    token_b = await _signup(client)

    await client.post("/v1/keys", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "a-key"})

    resp_a = await client.get("/v1/keys", headers={"Authorization": f"Bearer {token_a}"})
    resp_b = await client.get("/v1/keys", headers={"Authorization": f"Bearer {token_b}"})
    assert len(resp_a.json()) == 1
    assert len(resp_b.json()) == 0


@pytest.mark.asyncio
async def test_revoke_key_marks_it_unusable(client):
    token = await _signup(client)
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "to revoke"}
    )
    key_id = create.json()["id"]
    raw_key = create.json()["key"]

    revoke = await client.delete(f"/v1/keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert revoke.status_code == 204

    search = await client.get("/v1/search", params={"q": "test"}, headers={"X-API-Key": raw_key})
    assert search.status_code == 401


@pytest.mark.asyncio
async def test_revoke_key_not_owned_returns_404(client):
    token_a = await _signup(client)
    token_b = await _signup(client)
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "a-key"}
    )
    key_id = create.json()["id"]

    resp = await client.delete(f"/v1/keys/{key_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_without_api_key_rejected(client):
    resp = await client.get("/v1/search", params={"q": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_search_with_valid_api_key_reaches_provider(client):
    """No real SearXNG upstream is running in tests, so a valid key should
    get past auth and fail at the provider (502), not at auth (401)."""
    token = await _signup(client)
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "search key"}
    )
    raw_key = create.json()["key"]

    resp = await client.get("/v1/search", params={"q": "test"}, headers={"X-API-Key": raw_key})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_search_accepts_bearer_api_key_too(client):
    token = await _signup(client)
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "bearer key"}
    )
    raw_key = create.json()["key"]

    resp = await client.get(
        "/v1/search", params={"q": "test"}, headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert resp.status_code == 502
