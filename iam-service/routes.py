from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_token, decode_token, hash_password, verify_password
from database import get_db
from models import User
from schemas import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ValidateRequest,
    ValidateResponse,
)

router = APIRouter()


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Rate limiting is NOT handled here — it is enforced at the API Gateway.
    # Adding it here would duplicate logic and couple this service to a policy
    # that belongs at the edge.
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Rate limiting is NOT handled here — it is enforced at the API Gateway.
    # Brute-force protection (e.g. N failed attempts per IP) also belongs there.
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_token(user_id=user.id, email=user.email, role=user.role)
    return LoginResponse(access_token=token)


@router.post("/validate", response_model=ValidateResponse)
async def validate(body: ValidateRequest):
    payload = decode_token(body.token)
    if not payload:
        return ValidateResponse(valid=False)

    return ValidateResponse(
        valid=True,
        user_id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
    )
