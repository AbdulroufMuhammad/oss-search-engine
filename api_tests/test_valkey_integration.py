"""Tests against a real local redis-server process (Valkey speaks the same
protocol), not just the in-process fallback. These specifically prove the
thing the fallback can't: two separate client instances - standing in for
two separate API instances behind a load balancer - see the same counters
and cache when backed by Valkey/Redis, which is the actual bug being fixed
for a multi-instance AWS deployment.

Skips (rather than fails) if no `redis-server` binary is available, since
that's an environment/tooling gap, not a code regression.
"""

import shutil
import socket
import subprocess
import time
import uuid

import pytest
import pytest_asyncio
import valkey.asyncio as valkey

from api import cache, ratelimit, valkeydb
from api.models.search import SearchResponse, SearchResult

pytestmark = pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server not installed")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def redis_port():
    port = _free_port()
    proc = subprocess.Popen(
        ["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        up = False
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    up = True
                    break
            except OSError:
                time.sleep(0.05)
        if not up:
            proc.terminate()
            pytest.skip("redis-server did not start in time")
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest_asyncio.fixture
async def two_clients(redis_port):
    """Two independent client connections to the same server, standing in
    for two separate API instances."""
    client_a = valkey.Valkey.from_url(f"redis://127.0.0.1:{redis_port}")
    client_b = valkey.Valkey.from_url(f"redis://127.0.0.1:{redis_port}")
    yield client_a, client_b
    await client_a.aclose()
    await client_b.aclose()


@pytest_asyncio.fixture
async def as_instance_a(two_clients, monkeypatch):
    client_a, _ = two_clients
    monkeypatch.setattr(valkeydb, "_client", client_a)


@pytest_asyncio.fixture
async def as_instance_b(two_clients, monkeypatch):
    _, client_b = two_clients
    monkeypatch.setattr(valkeydb, "_client", client_b)


@pytest.mark.asyncio
async def test_valkey_ratelimit_allows_under_limit(as_instance_a):
    key_id = uuid.uuid4().hex
    for _ in range(3):
        allowed, retry_after = await ratelimit.check_and_increment(key_id, limit_per_minute=3)
        assert allowed is True
        assert retry_after == 0


@pytest.mark.asyncio
async def test_valkey_ratelimit_blocks_over_limit_with_retry_after(as_instance_a):
    key_id = uuid.uuid4().hex
    for _ in range(2):
        assert (await ratelimit.check_and_increment(key_id, limit_per_minute=2))[0] is True

    allowed, retry_after = await ratelimit.check_and_increment(key_id, limit_per_minute=2)
    assert allowed is False
    assert 0 < retry_after <= 60


@pytest.mark.asyncio
async def test_valkey_ratelimit_shared_across_two_instances(two_clients, monkeypatch):
    """The actual bug being fixed: with the in-memory fallback, instance B
    would have no idea instance A already used up the quota. Backed by
    Valkey, they share one counter."""
    client_a, client_b = two_clients
    key_id = uuid.uuid4().hex

    monkeypatch.setattr(valkeydb, "_client", client_a)
    assert (await ratelimit.check_and_increment(key_id, limit_per_minute=2))[0] is True
    assert (await ratelimit.check_and_increment(key_id, limit_per_minute=2))[0] is True

    # Switch to "instance B" - a fresh in-process counter would allow this;
    # the shared Valkey counter correctly blocks it.
    monkeypatch.setattr(valkeydb, "_client", client_b)
    allowed, retry_after = await ratelimit.check_and_increment(key_id, limit_per_minute=2)
    assert allowed is False
    assert retry_after > 0


@pytest.mark.asyncio
async def test_valkey_cache_roundtrip(as_instance_a):
    query = f"valkey cache query {uuid.uuid4().hex}"
    resp = SearchResponse(
        query=query,
        answer="an answer",
        results=[SearchResult(title="t", url="https://example.com", content="c")],
        response_time=0.05,
    )
    await cache.set(query, 10, resp)
    cached = await cache.get(query, 10)
    assert cached is not None
    assert cached.query == query
    assert cached.answer == "an answer"
    assert cached.results[0].url == "https://example.com"


@pytest.mark.asyncio
async def test_valkey_cache_miss_returns_none(as_instance_a):
    assert await cache.get(f"never cached {uuid.uuid4().hex}", 10) is None


@pytest.mark.asyncio
async def test_valkey_cache_shared_across_two_instances(two_clients, monkeypatch):
    client_a, client_b = two_clients
    query = f"shared cache query {uuid.uuid4().hex}"
    resp = SearchResponse(
        query=query, answer=None, results=[], response_time=0.01
    )

    monkeypatch.setattr(valkeydb, "_client", client_a)
    await cache.set(query, 10, resp)

    # A different "instance" reads the same cache entry back.
    monkeypatch.setattr(valkeydb, "_client", client_b)
    cached = await cache.get(query, 10)
    assert cached is not None
    assert cached.query == query
