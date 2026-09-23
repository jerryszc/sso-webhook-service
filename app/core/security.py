import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _build_token(
    subject: str, expires: timedelta, token_type: str, extra: dict[str, Any] | None = None
) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "jti": jti,
        "type": token_type,
        "iat": now,
        "exp": now + expires,
        **(extra or {}),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)
    return token, jti


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, str]:
    return _build_token(subject, timedelta(minutes=settings.access_token_minutes), "access", extra)


def create_refresh_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, str]:
    return _build_token(subject, timedelta(days=settings.refresh_token_days), "refresh", extra)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
