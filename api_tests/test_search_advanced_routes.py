import uuid

import pytest

import api.routes.search as search_route
from api.models.document import Document, Passage
from api.models.search import ImageResult, SearchResponse, SearchResult


class _FakeProvider:
    def __init__(self, results, images=None):
        self._results = results
        self._images = images or []
        self.last_search_kwargs = None

    async def search(self, query, **kwargs):
        self.last_search_kwargs = kwargs
        return SearchResponse(query=query, results=list(self._results), response_time=0.01)

    async def search_expanded(self, query, **kwargs):
        return await self.search(query, **kwargs)

    async def search_images(self, query, **kwargs):
        return list(self._images)


def _weak_score_result(url="https://a.example.com", title="A") -> SearchResult:
    # A low snippet-based score, so an "advanced" re-score against a much
    # richer full-text document is visibly different, not a no-op.
    return SearchResult(title=title, url=url, content="x", final_score=0.1)


async def _signup_and_get_key(client) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]
    create = await client.post(
        "/v1/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "advanced-test"}
    )
    return create.json()["key"]


def _install(monkeypatch, provider):
    from api.app import app

    monkeypatch.setattr(app.state, "search_provider", provider)


@pytest.mark.asyncio
async def test_search_depth_rejects_invalid_value(client):
    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search", params={"q": "test", "search_depth": "extreme"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_depth_basic_is_default_and_never_fetches(client, monkeypatch):
    _install(monkeypatch, _FakeProvider([_weak_score_result()]))

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("extract_document should not be called for search_depth=basic")

    monkeypatch.setattr(search_route, "extract_document", fail_if_called)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search", params={"q": "depth-basic-default-test"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["raw_content"] is None


@pytest.mark.asyncio
async def test_search_depth_advanced_fetches_and_rescales_ranking(client, monkeypatch):
    _install(
        monkeypatch,
        _FakeProvider(
            [
                _weak_score_result("https://weak.example.com", "Weak"),
                SearchResult(title="Strong", url="https://strong.example.com", content="x", final_score=0.9),
            ]
        ),
    )

    async def fake_extract(url, client_, query=None, max_passages=None):
        # the "weak" snippet result actually has a long, on-topic full page
        if url == "https://weak.example.com":
            content = ("depth-advanced-rescale-test " * 50).strip()
        else:
            content = "unrelated"
        return Document(url=url, word_count=len(content.split()), content=content, passages=[])

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "depth-advanced-rescale-test", "search_depth": "advanced"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    # both got raw_content attached (absorbs include_raw_content's job)
    assert all(r["raw_content"] is not None for r in results)
    # re-scored from full content: the long, on-topic page now outranks
    # the one whose full page turned out unrelated to the query
    assert results[0]["url"] == "https://weak.example.com"


@pytest.mark.asyncio
async def test_search_depth_advanced_does_not_double_fetch_with_include_raw_content(client, monkeypatch):
    calls = {"n": 0}
    _install(monkeypatch, _FakeProvider([_weak_score_result()]))

    async def fake_extract(url, client_, query=None, max_passages=None):
        calls["n"] += 1
        return Document(url=url, word_count=1, content="full", passages=[])

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "depth-no-double-fetch-test", "search_depth": "advanced", "include_raw_content": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_chunks_per_source_populates_content_chunks(client, monkeypatch):
    _install(monkeypatch, _FakeProvider([_weak_score_result()]))

    async def fake_extract(url, client_, query=None, max_passages=None):
        assert max_passages == 3
        return Document(
            url=url,
            word_count=10,
            content="full content",
            passages=[
                Passage(text="chunk one", score=0.9, start=0, end=9),
                Passage(text="chunk two", score=0.5, start=10, end=19),
            ],
        )

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "chunks-per-source-test", "search_depth": "advanced", "chunks_per_source": 3},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["content_chunks"] == ["chunk one", "chunk two"]


@pytest.mark.asyncio
async def test_chunks_per_source_clamped_to_max(client, monkeypatch):
    _install(monkeypatch, _FakeProvider([_weak_score_result()]))
    captured = {}

    async def fake_extract(url, client_, query=None, max_passages=None):
        captured["max_passages"] = max_passages
        return Document(url=url, word_count=1, content="c", passages=[])

    monkeypatch.setattr(search_route, "extract_document", fake_extract)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "chunks-clamped-test", "search_depth": "advanced", "chunks_per_source": 999},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert captured["max_passages"] == 10  # MAX_CHUNKS_PER_SOURCE


@pytest.mark.asyncio
async def test_chunks_per_source_ignored_without_advanced_depth(client, monkeypatch):
    """chunks_per_source needs the full-text fetch that only search_depth=
    advanced triggers - passing it alone (basic depth) must not fetch."""
    _install(monkeypatch, _FakeProvider([_weak_score_result()]))

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("extract_document should not be called for search_depth=basic")

    monkeypatch.setattr(search_route, "extract_document", fail_if_called)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "chunks-without-advanced-test", "chunks_per_source": 3},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["content_chunks"] is None


@pytest.mark.asyncio
async def test_include_image_descriptions_mirrors_title(client, monkeypatch):
    _install(
        monkeypatch,
        _FakeProvider(
            [_weak_score_result()],
            images=[ImageResult(title="A cat", url="https://a.example.com", image_url="https://a.example.com/cat.jpg")],
        ),
    )

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "image-desc-test", "include_images": True, "include_image_descriptions": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["images"][0]["description"] == "A cat"


@pytest.mark.asyncio
async def test_include_image_descriptions_false_by_default(client, monkeypatch):
    _install(
        monkeypatch,
        _FakeProvider(
            [_weak_score_result()],
            images=[ImageResult(title="A cat", url="https://a.example.com", image_url="https://a.example.com/cat.jpg")],
        ),
    )

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search",
        params={"q": "image-desc-default-test", "include_images": True},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["images"][0]["description"] is None


@pytest.mark.asyncio
async def test_country_forwarded_to_provider(client, monkeypatch):
    provider = _FakeProvider([_weak_score_result()])
    _install(monkeypatch, provider)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search", params={"q": "country-forward-test", "country": "japan"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    assert provider.last_search_kwargs["country"] == "japan"


@pytest.mark.asyncio
async def test_country_omitted_is_none(client, monkeypatch):
    provider = _FakeProvider([_weak_score_result()])
    _install(monkeypatch, provider)

    api_key = await _signup_and_get_key(client)
    resp = await client.get(
        "/v1/search", params={"q": "country-omitted-test"}, headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    assert provider.last_search_kwargs["country"] is None
