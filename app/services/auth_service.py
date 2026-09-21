from datetime import datetime, timedelta, timezone

import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.service_client import ServiceClient
from app.models.user import User


class AuthError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def register_user(session: AsyncSession, email: str, password: str) -> User:
    existing = (await session.exec(select(User).where(User.email == email))).first()
    if existing is not None:
        raise AuthError("Email already registered")
    user = User(email=email, password_hash=hash_password(password), role="user", is_active=True)
    session.add(user)
    await session.flush()
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User:
    result = await session.exec(select(User).where(User.email == email))
    user = result.first()
    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        raise AuthError("Invalid credentials")
    return user


async def _store_refresh(
    session: AsyncSession, *, user_id: str | None, client_db_id: str | None, jti: str
) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days)
    session.add(
        RefreshToken(
            user_id=user_id, service_client_id=client_db_id, jti=jti, expires_at=expires_at
        )
    )
    await session.flush()


async def issue_user_tokens(session: AsyncSession, user: User) -> tuple[str, str]:
    access, _ = create_access_token(f"user:{user.id}", {"role": user.role})
    refresh, jti = create_refresh_token(f"user:{user.id}")
    await _store_refresh(session, user_id=user.id, client_db_id=None, jti=jti)
    return access, refresh


async def rotate_refresh(session: AsyncSession, refresh_token: str) -> tuple[str, str]:
    try:
        payload = decode_token(refresh_token)
    except jwt.ExpiredSignatureError:
        raise AuthError("Refresh expired")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid refresh token")
    if payload.get("type") != "refresh":
        raise AuthError("Invalid token type")

    jti: str = payload.get("jti", "")
    client = get_redis()
    if await client.exists(f"blacklist:refresh:{jti}") == 1:
        raise AuthError("Refresh revoked")
    stored = (await session.exec(select(RefreshToken).where(RefreshToken.jti == jti))).first()
    if stored is None or stored.revoked:
        raise AuthError("Refresh revoked")

    sub: str = payload.get("sub", "")
    kind, _, identifier = sub.partition(":")
    if kind != "user":
        raise AuthError("Unsupported subject")

    result = await session.exec(select(User).where(User.id == identifier))
    user = result.first()
    if user is None or not user.is_active:
        raise AuthError("User inactive")

    # Revoke old
    stored.revoked = True
    ttl = int(timedelta(days=settings.refresh_token_days).total_seconds())
    await client.setex(f"blacklist:refresh:{jti}", ttl, "1")

    access, _ = create_access_token(f"user:{user.id}", {"role": user.role})
    new_refresh, new_jti = create_refresh_token(f"user:{user.id}")
    await _store_refresh(session, user_id=user.id, client_db_id=None, jti=new_jti)
    # link rotation
    rotated = (await session.exec(select(RefreshToken).where(RefreshToken.jti == new_jti))).first()
    if rotated is not None:
        rotated.rotated_from_jti = jti
    return access, new_refresh


async def revoke_refresh(session: AsyncSession, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token)
    except jwt.InvalidTokenError:
        raise AuthError("Invalid refresh token")
    jti: str = payload.get("jti", "")
    stored = (await session.exec(select(RefreshToken).where(RefreshToken.jti == jti))).first()
    if stored is not None:
        stored.revoked = True
    client = get_redis()
    ttl = int(timedelta(days=settings.refresh_token_days).total_seconds())
    await client.setex(f"blacklist:refresh:{jti}", ttl, "1")


async def issue_client_token(session: AsyncSession, client_id: str, secret: str) -> tuple[str, str]:
    result = await session.exec(select(ServiceClient).where(ServiceClient.client_id == client_id))
    client = result.first()
    if client is None or not client.is_active or not verify_password(secret, client.client_secret_hash):
        raise AuthError("Invalid client credentials")
    access, _ = create_access_token(f"client:{client.client_id}", {"scopes": client.scopes})
    return access, client.scopes
