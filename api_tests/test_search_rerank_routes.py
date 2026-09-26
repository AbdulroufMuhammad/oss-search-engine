import uuid

import pytest

import api.routes.search as search_route
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


def _results() -> list[SearchResult]:
    return [
        SearchResult(title="A", url="https://a.example.com", content="s", final_score=0.9),
        SearchResult(title="B", url="https://b.example.com", content="s", final_score=0.8),
    ]


def _install_fake_provider(monkeypatch, results):
    from api.app import app

    monkeypatch.setattr(app.state, "search_provider", _FakeProvider(results))


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "rerank-test"}
    )
    return create.json()["key"]


@pytest.mark.asyncio
async def test_semantic_rerank_false_by_default_does_not_call_reranker(client, monkeypatch):
    _install_fake_provider(monkeypatch, _results())

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("run_semantic_rerank should not be called when semantic_rerank is false")

    monkeypatch.setattr(search_route, "run_semantic_rerank", fail_if_called)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search", params={"q": "rerank-default-test"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    assert [r["title"] for r in resp.json()["results"]] == ["A", "B"]


@pytest.mark.asyncio
async def test_semantic_rerank_true_reorders_results(monkeypatch, client):
    _install_fake_provider(monkeypatch, _results())

    async def fake_rerank(query, results, http_client):
        return list(reversed(results))

    monkeypatch.setattr(search_route, "run_semantic_rerank", fake_rerank)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "rerank-true-test", "semantic_rerank": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert [r["title"] for r in resp.json()["results"]] == ["B", "A"]


@pytest.mark.asyncio
async def test_semantic_rerank_failure_keeps_original_order(monkeypatch, client):
    _install_fake_provider(monkeypatch, _results())

    async def fake_rerank(query, results, http_client):
        return None

    monkeypatch.setattr(search_route, "run_semantic_rerank", fake_rerank)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "rerank-failure-test", "semantic_rerank": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert [r["title"] for r in resp.json()["results"]] == ["A", "B"]


@pytest.mark.asyncio
async def test_semantic_rerank_skipped_for_a_single_result(monkeypatch, client):
    _install_fake_provider(monkeypatch, _results()[:1])

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("run_semantic_rerank should not be called for fewer than 2 results")

    monkeypatch.setattr(search_route, "run_semantic_rerank", fail_if_called)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "rerank-single-result-test", "semantic_rerank": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_semantic_rerank_changes_cache_key(monkeypatch, client):
    calls = {"n": 0}
    _install_fake_provider(monkeypatch, _results())

    async def fake_rerank(query, results, http_client):
        calls["n"] += 1
        return list(reversed(results))

    monkeypatch.setattr(search_route, "run_semantic_rerank", fake_rerank)

    api_key = await _signup_and_get_key(client)
    without = await client.get(
        "/v1/search", params={"q": "rerank-cache-key-test"}, headers={"X-API-Key": api_key}
    )
    with_rerank = await client.get(
        "/v1/search",
        params={"q": "rerank-cache-key-test", "semantic_rerank": True},
        headers={"X-API-Key": api_key},
    )
    assert [r["title"] for r in without.json()["results"]] == ["A", "B"]
    assert [r["title"] for r in with_rerank.json()["results"]] == ["B", "A"]
    assert calls["n"] == 1
