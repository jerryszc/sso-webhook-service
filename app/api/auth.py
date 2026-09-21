from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_principal
from app.core.config import settings
from app.core.ratelimit import rate_limiter
from app.schemas.auth import (
    ClientCredentialsRequest,
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services.auth_service import (
    AuthError,
    authenticate_user,
    confirm_password_reset,
    issue_client_token,
    issue_user_tokens,
    register_user,
    request_password_reset,
    revoke_refresh,
    rotate_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limiter("register"))],
)
async def register(
    request: Request, body: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> UserOut:
    ip = _get_client_ip(request)
    try:
        user = await register_user(session, body.email, body.password, ip)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    return UserOut(id=user.id, email=user.email, role=user.role, is_active=user.is_active)


@router.post("/login", response_model=TokenPair, dependencies=[Depends(rate_limiter("login"))])
async def login(
    request: Request, body: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenPair:
    ip = _get_client_ip(request)
    try:
        user = await authenticate_user(session, body.email, body.password, ip)
        access, refresh = await issue_user_tokens(session, user, ip)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    request: Request, body: RefreshRequest, session: AsyncSession = Depends(get_session)
) -> TokenPair:
    ip = _get_client_ip(request)
    try:
        access, new_refresh = await rotate_refresh(session, body.refresh_token, ip)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, body: LogoutRequest, session: AsyncSession = Depends(get_session)
) -> None:
    ip = _get_client_ip(request)
    try:
        await revoke_refresh(session, body.refresh_token, ip)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return None


@router.post(
    "/token",
    response_model=TokenPair,
    dependencies=[Depends(rate_limiter("token", max_requests=settings.rate_limit_token_per_minute))],
)
async def client_token(
    request: Request, body: ClientCredentialsRequest, session: AsyncSession = Depends(get_session)
) -> TokenPair:
    ip = _get_client_ip(request)
    try:
        access, _ = await issue_client_token(session, body.client_id, body.client_secret, ip)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    return TokenPair(access_token=access, refresh_token=None)


@router.post(
    "/password/reset",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter("password_reset"))],
)
async def password_reset_request(
    request: Request, body: PasswordResetRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    ip = _get_client_ip(request)
    try:
        user, token = await request_password_reset(session, body.email, ip)
        if user is None:
            # Always return success to not reveal if email exists
            return {"message": "If the email exists, a reset token has been generated"}
        return {"message": "Password reset token generated", "reset_token": token}
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.post(
    "/password/reset/confirm",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter("password_reset"))],
)
async def password_reset_confirm(
    request: Request, body: PasswordResetConfirm, session: AsyncSession = Depends(get_session)
) -> dict:
    ip = _get_client_ip(request)
    try:
        await confirm_password_reset(session, body.token, body.new_password, ip)
        return {"message": "Password has been reset successfully"}
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.get("/me", response_model=UserOut)
async def me(principal: dict = Depends(get_current_principal)) -> UserOut:
    if principal["kind"] != "user":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User token required")
    user = principal["user"]
    return UserOut(id=user.id, email=user.email, role=user.role, is_active=user.is_active)
