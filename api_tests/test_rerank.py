import httpx
import pytest

from api.llm import rerank
from api.models.search import SearchResult


def _results() -> list[SearchResult]:
    return [
        SearchResult(title="A", url="https://a.example.com", content="about apples"),
        SearchResult(title="B", url="https://b.example.com", content="about bananas"),
        SearchResult(title="C", url="https://c.example.com", content="about cherries"),
    ]


@pytest.mark.asyncio
async def test_returns_none_when_no_api_key_configured(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "")
    async with httpx.AsyncClient() as client:
        result = await rerank.semantic_rerank("query", _results(), client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_fewer_than_two_results(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")
    async with httpx.AsyncClient() as client:
        result = await rerank.semantic_rerank("query", _results()[:1], client)
    assert result is None


@pytest.mark.asyncio
async def test_reorders_results_by_model_order(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[2, 0, 1]"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reordered = await rerank.semantic_rerank("query", _results(), client)

    assert [r.title for r in reordered] == ["C", "A", "B"]


@pytest.mark.asyncio
async def test_handles_markdown_fenced_response(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "```json\n[1, 2, 0]\n```"}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reordered = await rerank.semantic_rerank("query", _results(), client)

    assert [r.title for r in reordered] == ["B", "C", "A"]


@pytest.mark.asyncio
async def test_ignores_invalid_indices_and_appends_omitted_ones(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        # 99 is out of range and should be dropped; index 1 never mentioned
        # so it should be appended at the end, after the valid pick (0).
        return httpx.Response(200, json={"choices": [{"message": {"content": "[0, 99]"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reordered = await rerank.semantic_rerank("query", _results(), client)

    assert [r.title for r in reordered] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_only_reorders_top_k_leaves_the_rest_untouched(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(rerank, "SEMANTIC_RERANK_TOP_K", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1, 0]"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reordered = await rerank.semantic_rerank("query", _results(), client)

    # only A and B (top 2) were candidates; C stays appended, untouched
    assert [r.title for r in reordered] == ["B", "A", "C"]


@pytest.mark.asyncio
async def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await rerank.semantic_rerank("query", _results(), client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_non_json_content(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not an order"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await rerank.semantic_rerank("query", _results(), client)
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(rerank, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await rerank.semantic_rerank("query", _results(), client)
    assert result is None
