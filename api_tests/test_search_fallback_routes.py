import uuid

import pytest

import api.routes.search as search_route
from api.providers.base import ProviderUnavailableError
from api.models.search import SearchResponse, SearchResult


class _FakeProvider:
    def __init__(self, results=None, raises: Exception | None = None):
        self._results = results or []
        self._raises = raises

    async def search(self, query, **kwargs):
        if self._raises is not None:
            raise self._raises
        return SearchResponse(query=query, results=list(self._results), response_time=0.01)

    async def search_expanded(self, query, **kwargs):
        return await self.search(query, **kwargs)

    async def search_images(self, query, **kwargs):
        return []


def _weak_result() -> SearchResult:
    return SearchResult(title="Weak", url="https://weak.example.com", content="s", final_score=0.1)


def _strong_result() -> SearchResult:
    return SearchResult(title="Strong", url="https://strong.example.com", content="s", final_score=0.9)


def _tavily_response() -> SearchResponse:
    return SearchResponse(
        query="q",
        results=[SearchResult(title="Tavily", url="https://tavily.example.com", content="s", final_score=0.8)],
        response_time=0.2,
    )


async def _fail_if_called(*args, **kwargs):
    raise AssertionError("tavily_search should not be called here")


def _install(monkeypatch, provider):
    from api.app import app

    monkeypatch.setattr(app.state, "search_provider", provider)


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "fallback-test"}
    )
    return create.json()["key"]


@pytest.mark.asyncio
async def test_fallback_not_triggered_when_result_is_strong(client, monkeypatch):
    _install(monkeypatch, _FakeProvider(results=[_strong_result()]))
    monkeypatch.setattr(search_route, "tavily_search", _fail_if_called)

    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/search", params={"q": "fallback-strong-test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] is False
    assert body["results"][0]["url"] == "https://strong.example.com"


@pytest.mark.asyncio
async def test_fallback_triggered_when_top_result_is_weak(client, monkeypatch):
    _install(monkeypatch, _FakeProvider(results=[_weak_result()]))

    async def fake_tavily(query, client_, *, max_results=10):
        return _tavily_response()

    monkeypatch.setattr(search_route, "tavily_search", fake_tavily)

    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/search", params={"q": "fallback-weak-test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] is True
    assert body["results"][0]["url"] == "https://tavily.example.com"


@pytest.mark.asyncio
async def test_fallback_triggered_when_results_are_empty(client, monkeypatch):
    _install(monkeypatch, _FakeProvider(results=[]))

    async def fake_tavily(query, client_, *, max_results=10):
        return _tavily_response()

    monkeypatch.setattr(search_route, "tavily_search", fake_tavily)

    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/search", params={"q": "fallback-empty-test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["fallback_used"] is True


@pytest.mark.asyncio
async def test_weak_result_kept_when_tavily_also_unavailable(client, monkeypatch):
    _install(monkeypatch, _FakeProvider(results=[_weak_result()]))

    async def fake_tavily(query, client_, *, max_results=10):
        return None

    monkeypatch.setattr(search_route, "tavily_search", fake_tavily)

    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/search", params={"q": "fallback-weak-no-tavily-test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] is False
    assert body["results"][0]["url"] == "https://weak.example.com"


@pytest.mark.asyncio
async def test_fallback_used_when_upstream_totally_unavailable(client, monkeypatch):
    _install(monkeypatch, _FakeProvider(raises=ProviderUnavailableError("down")))

    async def fake_tavily(query, client_, *, max_results=10):
        return _tavily_response()

    monkeypatch.setattr(search_route, "tavily_search", fake_tavily)

    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/search", params={"q": "fallback-upstream-down-test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] is True
    assert body["results"][0]["url"] == "https://tavily.example.com"


@pytest.mark.asyncio
async def test_502_when_upstream_down_and_tavily_unavailable_too(client, monkeypatch):
    _install(monkeypatch, _FakeProvider(raises=ProviderUnavailableError("down")))

    async def fake_tavily(query, client_, *, max_results=10):
        return None

    monkeypatch.setattr(search_route, "tavily_search", fake_tavily)

    api_key = await _signup_and_get_key(client)
    resp = await client.get("/v1/search", params={"q": "fallback-502-test"}, headers={"X-API-Key": api_key})
    assert resp.status_code == 502
