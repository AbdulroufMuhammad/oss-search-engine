import uuid

import pytest

import api.routes.search as search_route
from api.models.document import Document
from api.models.search import SearchResponse, SearchResult


class _FakeProvider:
    def __init__(self, results):
        self._results = results

    async def search(self, query, **kwargs):
        return SearchResponse(query=query, results=list(self._results), response_time=0.01)

    async def search_expanded(self, query, **kwargs):
        return await self.search(query, **kwargs)

    async def search_images(self, query, **kwargs):
        return []


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "raw-content-test"}
    )
    return create.json()["key"]


def _install_fake_provider(monkeypatch, results):
    from api.app import app

    monkeypatch.setattr(app.state, "search_provider", _FakeProvider(results))


@pytest.mark.asyncio
async def test_include_raw_content_false_by_default_leaves_field_null(client, monkeypatch):
    _install_fake_provider(
        monkeypatch, [SearchResult(title="A", url="https://a.example.com", content="snippet")]
    )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("extract_document should not be called when include_raw_content is false")

    monkeypatch.setattr(search_route, "extract_document", fail_if_called)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search", params={"q": "raw-content-default-test"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["raw_content"] is None


@pytest.mark.asyncio
async def test_include_raw_content_true_attaches_full_text(client, monkeypatch):
    _install_fake_provider(
        monkeypatch,
        [
            SearchResult(title="A", url="https://a.example.com", content="snippet a"),
            SearchResult(title="B", url="https://b.example.com", content="snippet b"),
        ],
    )

    async def fake_extract(url, client_, query=None, max_passages=None):
        return Document(url=url, word_count=3, content=f"full text for {url}", passages=[])

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "raw-content-full-text-test", "include_raw_content": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["raw_content"] == "full text for https://a.example.com"
    assert results[1]["raw_content"] == "full text for https://b.example.com"
    # the original snippet is untouched - raw_content is additive
    assert results[0]["content"] == "snippet a"


@pytest.mark.asyncio
async def test_include_raw_content_fails_soft_per_url(client, monkeypatch):
    _install_fake_provider(
        monkeypatch,
        [
            SearchResult(title="Good", url="https://good.example.com", content="s"),
            SearchResult(title="Bad", url="https://bad.example.com", content="s"),
        ],
    )

    async def fake_extract(url, client_, query=None, max_passages=None):
        if url == "https://bad.example.com":
            raise RuntimeError("fetch failed")
        return Document(url=url, word_count=1, content="ok", passages=[])

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "raw-content-fails-soft-test", "include_raw_content": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    good = next(r for r in results if r["url"] == "https://good.example.com")
    bad = next(r for r in results if r["url"] == "https://bad.example.com")
    assert good["raw_content"] == "ok"
    assert bad["raw_content"] is None


@pytest.mark.asyncio
async def test_include_raw_content_changes_cache_key(client, monkeypatch):
    """A cached response from include_raw_content=false must not be served
    back for include_raw_content=true, or vice versa."""
    calls = {"n": 0}

    _install_fake_provider(
        monkeypatch, [SearchResult(title="A", url="https://a.example.com", content="s")]
    )

    async def fake_extract(url, client_, query=None, max_passages=None):
        calls["n"] += 1
        return Document(url=url, word_count=1, content="raw", passages=[])

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    without = await client.get(
        "/v1/search", params={"q": "cache-key-test"}, headers={"X-API-Key": api_key}
    )
    with_raw = await client.get(
        "/v1/search",
        params={"q": "cache-key-test", "include_raw_content": True},
        headers={"X-API-Key": api_key},
    )
    assert without.json()["results"][0]["raw_content"] is None
    assert with_raw.json()["results"][0]["raw_content"] == "raw"
    assert calls["n"] == 1
