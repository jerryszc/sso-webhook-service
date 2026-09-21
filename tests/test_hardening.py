"""Hardening: /ready, rate-limit y seed admin. Requiere DB/Redis reales (contenedor)."""

import os
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.db import async_session_factory
from app.core.redis import get_redis
from app.main import app
from app.models.user import User


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _redis_available() -> bool:
    try:
        await get_redis().ping()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_ready_ok(client: AsyncClient) -> None:
    r = await client.get("/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["db"] == "ok" and body["redis"] == "ok"


@pytest.mark.asyncio
async def test_rate_limit_blocks() -> None:
    if not await _redis_available():
        pytest.skip("Sin Redis real")
    from app.core.ratelimit import check_rate_limit

    key = f"ratelimit:test:{uuid.uuid4().hex}"
    await check_rate_limit(key, 2, 60)
    await check_rate_limit(key, 2, 60)
    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(key, 2, 60)
    assert exc.value.status_code == 429
    await get_redis().delete(key)


@pytest.mark.asyncio
async def test_seed_admin_idempotent() -> None:
    from app.core.seed import seed_admin

    email = f"admin-{uuid.uuid4().hex[:8]}@test.com"
    os.environ["SEED_ADMIN_EMAIL"] = email
    os.environ["SEED_ADMIN_PASSWORD"] = "adminsecret123"
    try:
        await seed_admin()
        await seed_admin()  # segunda corrida: idempotente
        async with async_session_factory() as session:
            user = (await session.exec(select(User).where(User.email == email))).first()
            assert user is not None and user.role == "admin" and user.is_active
    finally:
        os.environ.pop("SEED_ADMIN_EMAIL", None)
        os.environ.pop("SEED_ADMIN_PASSWORD", None)
