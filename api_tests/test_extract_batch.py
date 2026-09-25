import uuid

import pytest

import api.routes.extract as extract_route
from api.extraction import NoContentError


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "batch"}
    )
    return create.json()["key"]


@pytest.mark.asyncio
async def test_batch_extract_requires_auth(client):
    resp = await client.post("/v1/extract/batch", json={"urls": ["https://example.com"]})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_batch_extract_rejects_empty_url_list(client):
    api_key = await _signup_and_get_key(client)
    resp = await client.post(
        "/v1/extract/batch", json={"urls": []}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_extract_rejects_too_many_urls(client):
    api_key = await _signup_and_get_key(client)
    urls = [f"https://example.com/{i}" for i in range(21)]  # MAX_BATCH_EXTRACT_URLS is 20
    resp = await client.post(
        "/v1/extract/batch", json={"urls": urls}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_batch_extract_mixes_success_and_per_url_errors(client, monkeypatch):
    from api.models.document import Document

    async def fake_extract(url, client_, query=None, max_passages=None):
        if url == "https://good.example.com":
            return Document(url=url, word_count=2, content="hi there", passages=[])
        raise NoContentError("no extractable article content found on this page")

    monkeypatch.setattr(extract_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.post(
        "/v1/extract/batch",
        json={"urls": ["https://good.example.com", "https://bad.example.com"]},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 2

    good = next(r for r in results if r["url"] == "https://good.example.com")
    assert good["document"]["content"] == "hi there"
    assert good["error"] is None

    bad = next(r for r in results if r["url"] == "https://bad.example.com")
    assert bad["document"] is None
    assert "no extractable article content" in bad["error"]


@pytest.mark.asyncio
async def test_batch_extract_one_unexpected_exception_does_not_fail_whole_batch(client, monkeypatch):
    from api.models.document import Document

    async def fake_extract(url, client_, query=None, max_passages=None):
        if url == "https://crashes.example.com":
            raise RuntimeError("boom")
        return Document(url=url, word_count=1, content="ok", passages=[])

    monkeypatch.setattr(extract_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.post(
        "/v1/extract/batch",
        json={"urls": ["https://crashes.example.com", "https://fine.example.com"]},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]

    crashed = next(r for r in results if r["url"] == "https://crashes.example.com")
    assert crashed["document"] is None
    assert "boom" in crashed["error"]

    fine = next(r for r in results if r["url"] == "https://fine.example.com")
    assert fine["error"] is None
    assert fine["document"]["content"] == "ok"


@pytest.mark.asyncio
async def test_batch_extract_preserves_url_order(client, monkeypatch):
    from api.models.document import Document

    async def fake_extract(url, client_, query=None, max_passages=None):
        return Document(url=url, word_count=1, content="ok", passages=[])

    monkeypatch.setattr(extract_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    urls = [f"https://example.com/{i}" for i in range(5)]
    resp = await client.post(
        "/v1/extract/batch", json={"urls": urls}, headers={"X-API-Key": api_key}
    )
    results = resp.json()["results"]
    assert [r["url"] for r in results] == urls
