import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.audit_log import AuditLog
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.service_client import ServiceClient
from app.models.user import User


class AuthError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _log_audit(
    event_type: str,
    user_id: str | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Log audit event. If session is provided, use it; otherwise use a separate session."""

    async def _do_log(s: AsyncSession) -> None:
        audit = AuditLog(user_id=user_id, ip=ip, event_type=event_type, meta=metadata or {})
        s.add(audit)
        await s.flush()

    if session is not None:
        await _do_log(session)
    else:
        async with async_session_factory() as audit_session:
            await _do_log(audit_session)
            await audit_session.commit()


async def register_user(
    session: AsyncSession, email: str, password: str, ip: str | None = None
) -> User:
    existing = (await session.exec(select(User).where(User.email == email))).first()
    if existing is not None:
        await _log_audit("login_failed", ip=ip, metadata={"reason": "email_exists", "email": email})
        raise AuthError("Email already registered")
    user = User(email=email, password_hash=hash_password(password), role="user", is_active=True)
    session.add(user)
    await session.flush()
    await _log_audit(
        "user_registered", user_id=user.id, ip=ip, metadata={"email": email}, session=session
    )
    return user


async def authenticate_user(
    session: AsyncSession, email: str, password: str, ip: str | None = None
) -> User:
    result = await session.exec(select(User).where(User.email == email))
    user = result.first()
    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        await _log_audit(
            "login_failed", ip=ip, metadata={"reason": "invalid_credentials", "email": email}
        )
        raise AuthError("Invalid credentials")
    await _log_audit("login_success", user_id=user.id, ip=ip, session=session)
    return user


async def _store_refresh(
    session: AsyncSession, *, user_id: str | None, client_db_id: str | None, jti: str
) -> None:
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    session.add(
        RefreshToken(
            user_id=user_id, service_client_id=client_db_id, jti=jti, expires_at=expires_at
        )
    )
    await session.flush()


async def issue_user_tokens(
    session: AsyncSession, user: User, ip: str | None = None
) -> tuple[str, str]:
    access, _ = create_access_token(f"user:{user.id}", {"role": user.role})
    refresh, jti = create_refresh_token(f"user:{user.id}")
    await _store_refresh(session, user_id=user.id, client_db_id=None, jti=jti)
    return access, refresh


async def rotate_refresh(
    session: AsyncSession, refresh_token: str, ip: str | None = None
) -> tuple[str, str]:
    try:
        payload = decode_token(refresh_token)
    except jwt.ExpiredSignatureError:
        raise AuthError("Refresh expired") from None
    except jwt.InvalidTokenError:
        raise AuthError("Invalid refresh token") from None
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

    await _log_audit("token_refreshed", user_id=user.id, ip=ip, session=session)
    return access, new_refresh


async def revoke_refresh(session: AsyncSession, refresh_token: str, ip: str | None = None) -> None:
    try:
        payload = decode_token(refresh_token)
    except jwt.InvalidTokenError:
        raise AuthError("Invalid refresh token") from None
    jti: str = payload.get("jti", "")
    sub: str = payload.get("sub", "")
    kind, _, identifier = sub.partition(":")
    stored = (await session.exec(select(RefreshToken).where(RefreshToken.jti == jti))).first()
    if stored is not None:
        stored.revoked = True
    client = get_redis()
    ttl = int(timedelta(days=settings.refresh_token_days).total_seconds())
    await client.setex(f"blacklist:refresh:{jti}", ttl, "1")

    if kind == "user":
        await _log_audit("logout", user_id=identifier, ip=ip, session=session)


async def issue_client_token(
    session: AsyncSession, client_id: str, secret: str, ip: str | None = None
) -> tuple[str, str]:
    result = await session.exec(select(ServiceClient).where(ServiceClient.client_id == client_id))
    client = result.first()
    if (
        client is None
        or not client.is_active
        or not verify_password(secret, client.client_secret_hash)
    ):
        await _log_audit(
            "m2m_token_generated", ip=ip, metadata={"client_id": client_id, "success": False}
        )
        raise AuthError("Invalid client credentials")
    access, _ = create_access_token(f"client:{client.client_id}", {"scopes": client.scopes})
    await _log_audit(
        "m2m_token_generated",
        ip=ip,
        metadata={"client_id": client_id, "success": True},
        session=session,
    )
    return access, client.scopes


async def request_password_reset(
    session: AsyncSession, email: str, ip: str | None = None
) -> tuple[User, str]:
    """Request a password reset. Returns (user, plain_token) for dev/testing."""
    result = await session.exec(select(User).where(User.email == email))
    user = result.first()
    if user is None:
        await _log_audit(
            "password_reset_requested", ip=ip, metadata={"email": email, "user_found": False}
        )
        # Don't reveal if user exists - return success anyway
        return None, ""  # type: ignore

    # Invalidate any existing unused tokens for this user
    existing_tokens = (
        await session.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used == False,  # noqa: E712
                PasswordResetToken.expires_at > datetime.now(UTC),
            )
        )
    ).all()
    for token in existing_tokens:
        token.used = True

    # Generate secure token
    plain_token = secrets.token_urlsafe(32)
    token_hash = hash_password(plain_token)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.password_reset_token_minutes)

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(reset_token)
    await session.flush()

    await _log_audit(
        "password_reset_requested",
        user_id=user.id,
        ip=ip,
        metadata={"email": email},
        session=session,
    )
    return user, plain_token


async def confirm_password_reset(
    session: AsyncSession, token: str, new_password: str, ip: str | None = None
) -> User:
    """Confirm password reset with token."""
    # Find the token by checking all unexpired, unused tokens
    tokens = (
        await session.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.used == False,  # noqa: E712
                PasswordResetToken.expires_at > datetime.now(UTC),
            )
        )
    ).all()

    reset_token = None
    for t in tokens:
        if verify_password(token, t.token_hash):
            reset_token = t
            break

    if reset_token is None:
        await _log_audit(
            "password_changed", ip=ip, metadata={"success": False, "reason": "invalid_token"}
        )
        raise AuthError("Invalid or expired reset token")

    # Mark token as used
    reset_token.used = True

    # Update user password
    user = (await session.exec(select(User).where(User.id == reset_token.user_id))).first()
    if user is None:
        raise AuthError("User not found")

    user.password_hash = hash_password(new_password)
    user.updated_at = datetime.now(UTC)
    session.add(user)

    await _log_audit(
        "password_changed", user_id=user.id, ip=ip, metadata={"success": True}, session=session
    )
    return user
