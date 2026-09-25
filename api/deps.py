from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import ratelimit
from api.db import get_session
from api.db_models import ApiKey, User
from api.security import decode_access_token, hash_api_key


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user


async def get_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    raw_key = x_api_key
    if not raw_key and authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization.split(" ", 1)[1]
    if not raw_key:
        raise HTTPException(
            status_code=401, detail="missing API key: pass X-API-Key or Authorization: Bearer <key>"
        )

    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key)))
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")

    allowed, retry_after = await ratelimit.check_and_increment(api_key.id, api_key.rate_limit_per_minute)
    if not allowed:
        raise HTTPException(
            status_code=429, detail="rate limit exceeded", headers={"Retry-After": str(retry_after)}
        )

    api_key.last_used_at = datetime.now(timezone.utc)
    await session.commit()
    return api_key
