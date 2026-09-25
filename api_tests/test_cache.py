import pytest

from api import cache
from api.models.search import SearchResponse, SearchResult


def _response(query: str) -> SearchResponse:
    return SearchResponse(
        query=query,
        answer=None,
        results=[SearchResult(title="t", url="https://example.com", content="c")],
        response_time=0.01,
    )


@pytest.mark.asyncio
async def test_cache_miss_when_never_set():
    assert await cache.get("never seen query xyz", 10) is None


@pytest.mark.asyncio
async def test_cache_hit_after_set():
    resp = _response("hit test query")
    await cache.set("hit test query", 10, resp)
    assert (await cache.get("hit test query", 10)).query == resp.query


@pytest.mark.asyncio
async def test_cache_miss_for_different_max_results():
    resp = _response("max results query")
    await cache.set("max results query", 10, resp)
    assert await cache.get("max results query", 20) is None


@pytest.mark.asyncio
async def test_cache_categories_none_and_images_do_not_collide():
    resp_images = _response("categories query")
    await cache.set("categories query", 10, resp_images, categories="images")
    assert await cache.get("categories query", 10, categories=None) is None
    assert (await cache.get("categories query", 10, categories="images")).query == resp_images.query


@pytest.mark.asyncio
async def test_cache_expand_true_and_false_do_not_collide():
    resp_expanded = _response("expand query")
    await cache.set("expand query", 10, resp_expanded, expand=True)
    assert await cache.get("expand query", 10, expand=False) is None
    assert (await cache.get("expand query", 10, expand=True)).query == resp_expanded.query


@pytest.mark.asyncio
async def test_cache_include_answer_true_and_false_do_not_collide():
    resp = _response("answer query")
    await cache.set("answer query", 10, resp, include_answer=True)
    assert await cache.get("answer query", 10, include_answer=False) is None
    assert (await cache.get("answer query", 10, include_answer=True)).query == resp.query


@pytest.mark.asyncio
async def test_cache_include_domains_do_not_collide():
    resp = _response("domain filtered query")
    await cache.set("domain filtered query", 10, resp, include_domains=["python.org"])
    assert await cache.get("domain filtered query", 10, include_domains=["other.org"]) is None
    assert (
        await cache.get("domain filtered query", 10, include_domains=["python.org"])
    ).query == resp.query


def test_cache_key_ignores_domain_list_order():
    key_a = cache._key("q", 10, None, False, False, include_domains=["a.com", "b.com"])
    key_b = cache._key("q", 10, None, False, False, include_domains=["b.com", "a.com"])
    assert key_a == key_b


@pytest.mark.asyncio
async def test_cache_time_range_and_topic_do_not_collide():
    resp = _response("timely query")
    await cache.set("timely query", 10, resp, time_range="week", topic="news")
    assert await cache.get("timely query", 10, time_range="month", topic="news") is None
    assert await cache.get("timely query", 10, time_range="week", topic="general") is None
    assert (
        await cache.get("timely query", 10, time_range="week", topic="news")
    ).query == resp.query


@pytest.mark.asyncio
async def test_cache_expired_entry_returns_none(monkeypatch):
    resp = _response("ttl query")
    await cache.set("ttl query", 10, resp)

    real_monotonic = cache.time.monotonic
    monkeypatch.setattr(cache.time, "monotonic", lambda: real_monotonic() + 100000)
    assert await cache.get("ttl query", 10) is None
