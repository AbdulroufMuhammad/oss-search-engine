import httpx
import pytest

from api.config import UPSTREAM_FAILURE_THRESHOLD
from api.providers.base import ProviderUnavailableError
from api.providers.upstream import UpstreamSearchProvider


def _handler_for(good_url: str):
    """Fails every host except `good_url` with a connect error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != httpx.URL(good_url).host:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"query": "q", "results": []})

    return handler


@pytest.mark.asyncio
async def test_search_fails_over_to_second_url_when_first_is_down():
    handler = _handler_for("http://good.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider(["http://bad.local", "http://good.local"], client)
        result = await provider.search("q")

    assert result.query == "q"


@pytest.mark.asyncio
async def test_search_raises_when_every_url_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider(["http://bad1.local", "http://bad2.local"], client)
        with pytest.raises(ProviderUnavailableError):
            await provider.search("q")


@pytest.mark.asyncio
async def test_single_string_base_url_still_works():
    """Back-compat: constructing with one string (not a list) must behave
    exactly as before this failover support was added."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"query": "q", "results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider("http://upstream.local", client)
        result = await provider.search("q")

    assert result.query == "q"


@pytest.mark.asyncio
async def test_a_healthy_url_recovers_failure_count_on_success():
    handler = _handler_for("http://good.local")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = UpstreamSearchProvider(["http://bad.local", "http://good.local"], client)
        await provider.search("q")

    assert provider._failure_counts["http://good.local"] == 0
    assert provider._failure_counts["http://bad.local"] == 1


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


def test_ordered_urls_puts_cooling_down_urls_last():
    provider = UpstreamSearchProvider(["http://a.local", "http://b.local"], _client())
    for _ in range(UPSTREAM_FAILURE_THRESHOLD):
        provider._record_failure("http://a.local")

    assert provider._ordered_urls() == ["http://b.local", "http://a.local"]


def test_record_success_clears_cooldown():
    provider = UpstreamSearchProvider(["http://a.local", "http://b.local"], _client())
    for _ in range(UPSTREAM_FAILURE_THRESHOLD):
        provider._record_failure("http://a.local")
    assert provider._ordered_urls()[0] == "http://b.local"

    provider._record_success("http://a.local")
    assert provider._ordered_urls() == ["http://a.local", "http://b.local"]


def test_below_threshold_failures_do_not_trigger_cooldown():
    provider = UpstreamSearchProvider(["http://a.local", "http://b.local"], _client())
    for _ in range(UPSTREAM_FAILURE_THRESHOLD - 1):
        provider._record_failure("http://a.local")

    assert provider._ordered_urls() == ["http://a.local", "http://b.local"]
