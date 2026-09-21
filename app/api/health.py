from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import async_session_factory
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with async_session_factory() as session:
            await session.exec(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "down"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    if all(v == "ok" for v in checks.values()):
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready", **checks})
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "not-ready", **checks})
