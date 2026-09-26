import httpx
import pytest

from api.providers.upstream import UpstreamSearchProvider


@pytest.mark.asyncio
async def test_search_forwards_time_range_to_upstream():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["time_range"] = request.url.params.get("time_range")
        return httpx.Response(200, json={"query": "q", "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider("http://upstream.local", client)
        await provider.search("q", time_range="week")

    assert captured["time_range"] == "week"


@pytest.mark.asyncio
async def test_search_omits_time_range_when_not_given():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["has_time_range"] = "time_range" in request.url.params
        return httpx.Response(200, json={"query": "q", "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider("http://upstream.local", client)
        await provider.search("q")

    assert captured["has_time_range"] is False


@pytest.mark.asyncio
async def test_search_images_parses_and_dedupes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("categories") == "images"
        return httpx.Response(
            200,
            json={
                "query": "cats",
                "results": [
                    {
                        "title": "A cat",
                        "url": "https://example.com/cat-page",
                        "img_src": "https://example.com/cat.jpg",
                        "thumbnail_src": "https://example.com/cat-thumb.jpg",
                    },
                    # duplicate image URL - should be deduped
                    {
                        "title": "A cat again",
                        "url": "https://example.com/cat-page-2",
                        "img_src": "https://example.com/cat.jpg",
                    },
                    # missing img_src - should be skipped
                    {"title": "Not an image", "url": "https://example.com/no-image"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider("http://upstream.local", client)
        images = await provider.search_images("cats")

    assert len(images) == 1
    assert images[0].image_url == "https://example.com/cat.jpg"
    assert images[0].thumbnail_url == "https://example.com/cat-thumb.jpg"
    assert images[0].url == "https://example.com/cat-page"


@pytest.mark.asyncio
async def test_search_images_respects_max_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": "cats",
                "results": [
                    {"title": f"cat {i}", "url": f"https://example.com/{i}", "img_src": f"https://example.com/{i}.jpg"}
                    for i in range(20)
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider("http://upstream.local", client)
        images = await provider.search_images("cats", max_results=3)

    assert len(images) == 3
