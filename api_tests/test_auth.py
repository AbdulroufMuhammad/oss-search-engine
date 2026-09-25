import uuid

import pytest


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


@pytest.mark.asyncio
async def test_signup_returns_token(client):
    resp = await client.post("/v1/auth/signup", json={"email": _email(), "password": "password123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


@pytest.mark.asyncio
async def test_signup_duplicate_email_is_rejected(client):
    email = _email()
    first = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    assert first.status_code == 201

    second = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_signup_short_password_rejected(client):
    resp = await client.post("/v1/auth/signup", json={"email": _email(), "password": "short"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_with_correct_credentials(client):
    email = _email()
    await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})

    resp = await client.post("/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


@pytest.mark.asyncio
async def test_login_with_wrong_password_rejected(client):
    email = _email()
    await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})

    resp = await client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_rejected(client):
    resp = await client.post("/v1/auth/login", json={"email": _email(), "password": "password123"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_token(client):
    resp = await client.get("/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_garbage_token(client):
    resp = await client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_current_user(client):
    email = _email()
    signup = await client.post("/v1/auth/signup", json={"email": email, "password": "password123"})
    token = signup.json()["access_token"]

    resp = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email
