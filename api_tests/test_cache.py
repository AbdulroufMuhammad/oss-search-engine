from api import cache
from api.models.search import SearchResponse, SearchResult


def _response(query: str) -> SearchResponse:
    return SearchResponse(
        query=query,
        answer=None,
        results=[SearchResult(title="t", url="https://example.com", content="c")],
        response_time=0.01,
    )


def test_cache_miss_when_never_set():
    assert cache.get("never seen query xyz", 10) is None


def test_cache_hit_after_set():
    resp = _response("hit test query")
    cache.set("hit test query", 10, resp)
    assert cache.get("hit test query", 10) is resp


def test_cache_miss_for_different_max_results():
    resp = _response("max results query")
    cache.set("max results query", 10, resp)
    assert cache.get("max results query", 20) is None


def test_cache_categories_none_and_images_do_not_collide():
    resp_images = _response("categories query")
    cache.set("categories query", 10, resp_images, categories="images")
    assert cache.get("categories query", 10, categories=None) is None
    assert cache.get("categories query", 10, categories="images") is resp_images


def test_cache_expand_true_and_false_do_not_collide():
    resp_expanded = _response("expand query")
    cache.set("expand query", 10, resp_expanded, expand=True)
    assert cache.get("expand query", 10, expand=False) is None
    assert cache.get("expand query", 10, expand=True) is resp_expanded


def test_cache_expired_entry_returns_none(monkeypatch):
    resp = _response("ttl query")
    cache.set("ttl query", 10, resp)

    real_monotonic = cache.time.monotonic
    monkeypatch.setattr(cache.time, "monotonic", lambda: real_monotonic() + 100000)
    assert cache.get("ttl query", 10) is None
