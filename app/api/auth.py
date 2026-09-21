from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_principal
from app.core.config import settings
from app.core.ratelimit import rate_limiter
from app.schemas.auth import (
    ClientCredentialsRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services.auth_service import (
    AuthError,
    authenticate_user,
    issue_client_token,
    issue_user_tokens,
    register_user,
    revoke_refresh,
    rotate_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limiter("register"))],
)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)) -> UserOut:
    try:
        user = await register_user(session, body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    return UserOut(id=user.id, email=user.email, role=user.role, is_active=user.is_active)


@router.post("/login", response_model=TokenPair, dependencies=[Depends(rate_limiter("login"))])
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenPair:
    try:
        user = await authenticate_user(session, body.email, body.password)
        access, refresh = await issue_user_tokens(session, user)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_session)) -> TokenPair:
    try:
        access, new_refresh = await rotate_refresh(session, body.refresh_token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, session: AsyncSession = Depends(get_session)) -> None:
    try:
        await revoke_refresh(session, body.refresh_token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return None


@router.post(
    "/token",
    response_model=TokenPair,
    dependencies=[Depends(rate_limiter("token", max_requests=settings.rate_limit_token_per_minute))],
)
async def client_token(
    body: ClientCredentialsRequest, session: AsyncSession = Depends(get_session)
) -> TokenPair:
    try:
        access, _ = await issue_client_token(session, body.client_id, body.client_secret)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenPair(access_token=access, refresh_token=None)


@router.get("/me", response_model=UserOut)
async def me(principal: dict = Depends(get_current_principal)) -> UserOut:
    if principal["kind"] != "user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User token required")
    user = principal["user"]
    return UserOut(id=user.id, email=user.email, role=user.role, is_active=user.is_active)
