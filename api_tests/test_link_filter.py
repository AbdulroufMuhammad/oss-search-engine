import httpx
import pytest

from api.llm import link_filter


def _candidates() -> list[str]:
    return ["https://example.com/pricing", "https://example.com/blog", "https://example.com/about"]


@pytest.mark.asyncio
async def test_returns_none_when_no_api_key_configured(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "")
    async with httpx.AsyncClient() as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_fewer_than_two_candidates(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")
    async with httpx.AsyncClient() as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates()[:1], client
        )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_too_many_candidates(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr(link_filter, "MAX_CANDIDATES_PER_CALL", 2)
    async with httpx.AsyncClient() as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result is None


@pytest.mark.asyncio
async def test_filters_to_the_indices_the_model_picked(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[0]"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result == ["https://example.com/pricing"]


@pytest.mark.asyncio
async def test_empty_array_means_follow_nothing(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result == []


@pytest.mark.asyncio
async def test_ignores_out_of_range_indices(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[0, 99]"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result == ["https://example.com/pricing"]


@pytest.mark.asyncio
async def test_handles_markdown_fenced_response(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n[1]\n```"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result == ["https://example.com/blog"]


@pytest.mark.asyncio
async def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_on_non_json_content(monkeypatch):
    monkeypatch.setattr(link_filter, "DEEPSEEK_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "sure, links 0 and 2"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await link_filter.filter_links_by_instructions(
            "only pricing", "Home", _candidates(), client
        )
    assert result is None
