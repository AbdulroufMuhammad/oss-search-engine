"""api_tests/test_keys.py already exercises the same auth dependency
(get_api_key) against /v1/search and /v1/extract. These four routes
(analyze, research, finance/search, events) are the extra feature modules
this repo has beyond Seekly's core - added later than search/extract, so
they need their own confirmation that the same auth gate was actually
wired onto them and not just left open.
"""

import uuid

import pytest


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "extra-routes"}
    )
    return create.json()["key"]


@pytest.mark.asyncio
async def test_analyze_requires_api_key(client):
    resp = await client.get("/v1/analyze", params={"q": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_research_requires_api_key(client):
    resp = await client.get("/v1/research", params={"q": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_finance_search_requires_api_key(client):
    resp = await client.get("/v1/finance/search", params={"q": "apple"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_events_requires_api_key(client):
    resp = await client.get("/v1/events", params={"q": "tesla"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_analyze_with_valid_key_succeeds(client):
    """analyze doesn't call the upstream search engine at all (pure local query
    analysis), so unlike research/finance/events it can be fully exercised
    in tests without a real upstream."""
    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/analyze", params={"q": "tesla stock news"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert "intent" in body
    assert "queries" in body


@pytest.mark.asyncio
async def test_research_with_valid_key_degrades_gracefully_without_upstream(client):
    """No real upstream in tests. Unlike search/extract/events,
    research degrades to a 200 with empty evidence/citations rather than
    erroring - it gathers per-subquestion with return_exceptions=True and
    just ends up with nothing to report. This asserts that documented
    behavior, not a guess."""
    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/research", params={"q": "test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence"] == []
    assert body["answer"] is None


@pytest.mark.asyncio
async def test_finance_search_with_valid_key_degrades_gracefully_without_upstream(client):
    """Same graceful-degradation shape as research: company/CIK lookups
    come from a local SEC EDGAR dataset (no upstream needed), but the news
    search sub-query fails soft to an empty list rather than a 502."""
    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/finance/search", params={"q": "apple"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    assert resp.json()["news"] == []


@pytest.mark.asyncio
async def test_events_with_valid_key_reaches_provider(client):
    """Unlike research/finance, events has no fallback path - an upstream
    outage should surface as a clean 502, not an unhandled 500."""
    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/events", params={"q": "tesla"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 502
