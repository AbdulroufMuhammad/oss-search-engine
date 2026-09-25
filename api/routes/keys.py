from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import DEFAULT_RATE_LIMIT_PER_MINUTE
from api.db import get_session
from api.db_models import ApiKey, User
from api.deps import get_current_user
from api.models.apikey import ApiKeyCreatedOut, ApiKeyCreateRequest, ApiKeyOut, ApiKeyUpdateRequest
from api.security import generate_api_key, hash_api_key

router = APIRouter(prefix="/v1/keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreatedOut, status_code=201)
async def create_key(
    body: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    raw_key = generate_api_key()
    key = ApiKey(
        user_id=user.id,
        name=body.name,
        key_prefix=raw_key[:12],
        key_hash=hash_api_key(raw_key),
        rate_limit_per_minute=body.rate_limit_per_minute or DEFAULT_RATE_LIMIT_PER_MINUTE,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(key).model_dump(), key=raw_key)


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def update_key(
    key_id: str,
    body: ApiKeyUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    key.rate_limit_per_minute = body.rate_limit_per_minute
    await session.commit()
    await session.refresh(key)
    return key


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked = True
    await session.commit()
