import uuid

import pytest

from api import ratelimit


@pytest.mark.asyncio
async def test_allows_requests_under_the_limit():
    key_id = uuid.uuid4().hex
    for _ in range(5):
        allowed, retry_after = await ratelimit.check_and_increment(key_id, limit_per_minute=5)
        assert allowed is True
        assert retry_after == 0


@pytest.mark.asyncio
async def test_blocks_requests_over_the_limit():
    key_id = uuid.uuid4().hex
    for _ in range(3):
        assert (await ratelimit.check_and_increment(key_id, limit_per_minute=3))[0] is True

    allowed, retry_after = await ratelimit.check_and_increment(key_id, limit_per_minute=3)
    assert allowed is False
    assert retry_after > 0


@pytest.mark.asyncio
async def test_different_keys_have_independent_limits():
    key_a, key_b = uuid.uuid4().hex, uuid.uuid4().hex
    assert (await ratelimit.check_and_increment(key_a, limit_per_minute=1))[0] is True
    assert (await ratelimit.check_and_increment(key_a, limit_per_minute=1))[0] is False
    assert (await ratelimit.check_and_increment(key_b, limit_per_minute=1))[0] is True


@pytest.mark.asyncio
async def test_search_endpoint_returns_429_once_key_limit_is_exceeded(client):
    from api.db import async_session
    from api.db_models import ApiKey, User
    from api.security import generate_api_key, hash_api_key, hash_password

    raw_key = generate_api_key()
    async with async_session() as session:
        user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash=hash_password("password123"))
        session.add(user)
        await session.flush()
        session.add(
            ApiKey(
                user_id=user.id,
                name="tight limit",
                key_prefix=raw_key[:12],
                key_hash=hash_api_key(raw_key),
                rate_limit_per_minute=1,
            )
        )
        await session.commit()

    headers = {"X-API-Key": raw_key}
    first = await client.get("/v1/search", params={"q": "test"}, headers=headers)
    assert first.status_code == 502  # past auth + rate limit, fails at the (absent) upstream

    second = await client.get("/v1/search", params={"q": "test"}, headers=headers)
    assert second.status_code == 429
    assert "Retry-After" in second.headers
