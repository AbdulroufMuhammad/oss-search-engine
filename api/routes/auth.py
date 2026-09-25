from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_session
from api.db_models import User
from api.deps import get_current_user
from api.models.auth import LoginRequest, SignupRequest, TokenResponse, UserOut
from api.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(body: SignupRequest, session: AsyncSession = Depends(get_session)):
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="an account with that email already exists")
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email)
