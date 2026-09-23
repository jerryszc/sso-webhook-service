"""Rate limiting fixed-window sobre Redis. Sin Redis disponible: fail-open (no bloquea)."""

from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.redis import get_redis


async def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    try:
        client = get_redis()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        if count > max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    except HTTPException:
        raise
    except Exception:
        return


def rate_limiter(scope: str, max_requests: int | None = None, window_seconds: int | None = None):  # type: ignore[no-untyped-def]
    limit = max_requests or settings.rate_limit_auth_per_minute
    window = window_seconds or settings.rate_limit_window_seconds

    async def dependency(request: Request) -> None:
        forwarded = request.headers.get("x-forwarded-for", "")
        ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else "unknown")
        )
        await check_rate_limit(f"ratelimit:{scope}:{ip}", limit, window)

    return dependency
