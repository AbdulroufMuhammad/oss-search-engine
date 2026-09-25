import pytest

from api.routes.search import _apply_topic, _parse_domain_list


def test_parse_domain_list_splits_and_normalizes():
    assert _parse_domain_list("Python.org, Docs.Python.org") == ["python.org", "docs.python.org"]


def test_parse_domain_list_none_when_empty():
    assert _parse_domain_list(None) is None
    assert _parse_domain_list("") is None
    assert _parse_domain_list("  ,  ,") is None


def test_apply_topic_general_leaves_categories_untouched():
    assert _apply_topic("science", "general") == "science"
    assert _apply_topic(None, "general") is None


def test_apply_topic_news_adds_news_category():
    assert _apply_topic(None, "news") == "news"


def test_apply_topic_news_merges_with_existing_categories():
    assert _apply_topic("science", "news") == "news,science"


def test_apply_topic_news_does_not_duplicate():
    assert _apply_topic("news", "news") == "news"


@pytest.mark.asyncio
async def test_search_rejects_invalid_topic(client):
    from api.db import async_session
    from api.db_models import ApiKey, User
    from api.security import generate_api_key, hash_api_key, hash_password
    import uuid

    raw_key = generate_api_key()
    async with async_session() as session:
        user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash=hash_password("password123"))
        session.add(user)
        await session.flush()
        session.add(
            ApiKey(user_id=user.id, name="k", key_prefix=raw_key[:12], key_hash=hash_api_key(raw_key))
        )
        await session.commit()

    resp = await client.get(
        "/v1/search", params={"q": "test", "topic": "sports"}, headers={"X-API-Key": raw_key}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_rejects_invalid_time_range(client):
    from api.db import async_session
    from api.db_models import ApiKey, User
    from api.security import generate_api_key, hash_api_key, hash_password
    import uuid

    raw_key = generate_api_key()
    async with async_session() as session:
        user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash=hash_password("password123"))
        session.add(user)
        await session.flush()
        session.add(
            ApiKey(user_id=user.id, name="k", key_prefix=raw_key[:12], key_hash=hash_api_key(raw_key))
        )
        await session.commit()

    resp = await client.get(
        "/v1/search", params={"q": "test", "time_range": "decade"}, headers={"X-API-Key": raw_key}
    )
    assert resp.status_code == 400
