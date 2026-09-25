import httpx
import pytest

from api.llm import deepseek
from api.models.search import SearchResult


def _result() -> SearchResult:
    return SearchResult(title="Example", url="https://example.com", content="Some content about the query.")


@pytest.mark.asyncio
async def test_returns_none_when_no_api_key_configured(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_API_KEY", "")
    async with httpx.AsyncClient() as client:
        answer = await deepseek.synthesize_answer("query", [_result()], client)
    assert answer is None


@pytest.mark.asyncio
async def test_returns_none_when_no_results(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_API_KEY", "sk-test")
    async with httpx.AsyncClient() as client:
        answer = await deepseek.synthesize_answer("query", [], client)
    assert answer is None


@pytest.mark.asyncio
async def test_returns_synthesized_answer_on_success(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={"choices": [{"message": {"content": "  Synthesized answer.  "}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        answer = await deepseek.synthesize_answer("query", [_result()], client)
    assert answer == "Synthesized answer."


@pytest.mark.asyncio
async def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        answer = await deepseek.synthesize_answer("query", [_result()], client)
    assert answer is None


@pytest.mark.asyncio
async def test_returns_none_on_malformed_response(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        answer = await deepseek.synthesize_answer("query", [_result()], client)
    assert answer is None


@pytest.mark.asyncio
async def test_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr(deepseek, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        answer = await deepseek.synthesize_answer("query", [_result()], client)
    assert answer is None
