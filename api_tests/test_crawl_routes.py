import uuid

import pytest

import api.routes.crawl as crawl_route


async def _fake_run_job(job_id, timeout_seconds):
    """Replaces the real background crawl for route-level tests, which
    only need to check auth/validation/ownership/persistence of the job
    row itself, not real crawling."""


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "crawl-test"}
    )
    return create.json()["key"]


@pytest.mark.asyncio
async def test_create_crawl_requires_auth(client):
    resp = await client.post("/v1/crawl", json={"url": "https://example.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_map_requires_auth(client):
    resp = await client.post("/v1/map", json={"url": "https://example.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_crawl_rejects_unsafe_url(client):
    """The SSRF guard runs for real here (not mocked) - a private/loopback
    target must be rejected before any job row is even created."""
    api_key = await _signup_and_get_key(client)
    resp = await client.post(
        "/v1/crawl", json={"url": "http://127.0.0.1:9/x"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_crawl_rejects_max_pages_over_ceiling(client):
    api_key = await _signup_and_get_key(client)
    resp = await client.post(
        "/v1/crawl",
        json={"url": "https://example.com", "max_pages": 999999},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_crawl_returns_queued_job(client, monkeypatch):
    monkeypatch.setattr(crawl_route, "run_job", _fake_run_job)
    api_key = await _signup_and_get_key(client)

    resp = await client.post(
        "/v1/crawl", json={"url": "https://example.com"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["mode"] == "crawl"
    assert body["status"] == "queued"
    assert body["results"] is None


@pytest.mark.asyncio
async def test_create_map_returns_queued_job(client, monkeypatch):
    monkeypatch.setattr(crawl_route, "run_job", _fake_run_job)
    api_key = await _signup_and_get_key(client)

    resp = await client.post(
        "/v1/map", json={"url": "https://example.com"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 201
    assert resp.json()["mode"] == "map"


@pytest.mark.asyncio
async def test_get_crawl_job_not_found(client):
    api_key = await _signup_and_get_key(client)
    resp = await client.get(f"/v1/crawl/{uuid.uuid4().hex}", headers={"X-API-Key": api_key})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_crawl_job_ownership_isolation(client, monkeypatch):
    monkeypatch.setattr(crawl_route, "run_job", _fake_run_job)
    owner_key = await _signup_and_get_key(client)
    other_key = await _signup_and_get_key(client)

    create = await client.post(
        "/v1/crawl", json={"url": "https://example.com"}, headers={"X-API-Key": owner_key}
    )
    job_id = create.json()["id"]

    own_lookup = await client.get(f"/v1/crawl/{job_id}", headers={"X-API-Key": owner_key})
    assert own_lookup.status_code == 200

    other_lookup = await client.get(f"/v1/crawl/{job_id}", headers={"X-API-Key": other_key})
    assert other_lookup.status_code == 404


@pytest.mark.asyncio
async def test_map_job_not_visible_via_crawl_endpoint_id_mismatch_is_fine(client, monkeypatch):
    """/v1/map/{id} and /v1/crawl/{id} share a lookup implementation keyed
    only by job id + owner, so either path can fetch either mode's job -
    this documents that as intentional, not a bug to fix."""
    monkeypatch.setattr(crawl_route, "run_job", _fake_run_job)
    api_key = await _signup_and_get_key(client)

    create = await client.post(
        "/v1/map", json={"url": "https://example.com"}, headers={"X-API-Key": api_key}
    )
    job_id = create.json()["id"]

    via_crawl_path = await client.get(f"/v1/crawl/{job_id}", headers={"X-API-Key": api_key})
    assert via_crawl_path.status_code == 200
    assert via_crawl_path.json()["mode"] == "map"
