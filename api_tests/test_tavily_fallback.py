import httpx
import pytest

from api.providers import tavily


@pytest.mark.asyncio
async def test_returns_none_when_no_api_key_configured(monkeypatch):
    monkeypatch.setattr(tavily, "TAVILY_API_KEY", "")
    async with httpx.AsyncClient() as client:
        result = await tavily.tavily_search("query", client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_reshaped_response_on_success(monkeypatch):
    monkeypatch.setattr(tavily, "TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tvly-test"
        return httpx.Response(
            200,
            json={
                "answer": "A synthesized answer.",
                "results": [
                    {
                        "title": "Result A",
                        "url": "https://a.example.com",
                        "content": "Content A",
                        "score": 0.92,
                        "published_date": "2025-01-02",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tavily.tavily_search("query", client)

    assert result is not None
    assert result.query == "query"
    assert result.answer == "A synthesized answer."
    assert result.results[0].url == "https://a.example.com"
    assert result.results[0].final_score == 0.92
    assert result.results[0].published_at == "2025-01-02"


@pytest.mark.asyncio
async def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(tavily, "TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tavily.tavily_search("query", client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(tavily, "TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tavily.tavily_search("query", client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(tavily, "TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tavily.tavily_search("query", client)
    assert result is None


@pytest.mark.asyncio
async def test_skips_results_missing_a_url(monkeypatch):
    monkeypatch.setattr(tavily, "TAVILY_API_KEY", "tvly-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"title": "no url"}, {"title": "ok", "url": "https://a.example.com"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await tavily.tavily_search("query", client)

    assert len(result.results) == 1
    assert result.results[0].url == "https://a.example.com"
