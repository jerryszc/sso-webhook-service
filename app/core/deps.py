import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.redis import get_redis
from app.models.service_client import ServiceClient
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


async def _is_blacklisted(jti: str, token_type: str) -> bool:
    client = get_redis()
    key = f"blacklist:{token_type}:{jti}"
    try:
        return await client.exists(key) == 1
    except Exception:
        return False


async def get_current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    token_type: str = payload.get("type", "access")
    if token_type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    if await _is_blacklisted(payload.get("jti", ""), "access"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    sub: str = payload.get("sub", "")
    kind, _, identifier = sub.partition(":")
    if kind == "user":
        result = await session.exec(select(User).where(User.id == identifier))
        user = result.first()
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")
        return {"kind": "user", "user": user, "scopes": payload.get("scopes", "")}
    if kind == "client":
        result = await session.exec(
            select(ServiceClient).where(ServiceClient.client_id == identifier)
        )
        client = result.first()
        if client is None or not client.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client inactive")
        return {"kind": "client", "client": client, "scopes": payload.get("scopes", "")}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject")


def require_role(role: str):  # type: ignore[no-untyped-def]
    async def checker(principal: dict = Depends(get_current_principal)) -> dict:
        if principal["kind"] != "user" or principal["user"].role != role:
            # admin bypass: admin puede todo; user solo si role coincide
            if not (principal["kind"] == "user" and principal["user"].role == "admin"):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return principal

    return checker
