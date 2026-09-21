"""Integración contra PostgreSQL/Redis reales. Solo corre en contenedor (db/redis por nombre de servicio)."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.db import async_session_factory
from app.core.security import hash_password
from app.main import app
from app.models.service_client import ServiceClient


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _email() -> str:
    return f"it-{uuid.uuid4().hex[:10]}@test.com"


@pytest.mark.asyncio
async def test_register_login_me_refresh_logout(client: AsyncClient) -> None:
    email = _email()
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    assert r.status_code == 201, r.text

    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    assert r.status_code == 200, r.text
    access, refresh = r.json()["access_token"], r.json()["refresh_token"]

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200 and r.json()["email"] == email

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    new_refresh = r.json()["refresh_token"]

    # refresh viejo rotado -> 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401

    r = await client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_client_credentials_flow(client: AsyncClient) -> None:
    cid = f"tc-{uuid.uuid4().hex[:8]}"
    secret = "tc-secret-1234567890"
    async with async_session_factory() as session:
        session.add(ServiceClient(client_id=cid, client_secret_hash=hash_password(secret), scopes="webhooks:publish"))
        await session.commit()

    r = await client.post("/api/v1/auth/token", json={"client_id": cid, "client_secret": secret})
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"] is None

    r = await client.post("/api/v1/auth/token", json={"client_id": cid, "client_secret": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_publish_idempotent(client: AsyncClient) -> None:
    email = _email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    tok = (await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})).json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}", "Idempotency-Key": f"it-{uuid.uuid4()}"}

    body = {"type": "user.created", "payload": {"email": email}}
    r1 = await client.post("/api/v1/webhooks/events", json=body, headers=headers)
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/api/v1/webhooks/events", json=body, headers=headers)
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]

    # sin Idempotency-Key -> 422
    r3 = await client.post("/api/v1/webhooks/events", json=body, headers={"Authorization": f"Bearer {tok}"})
    assert r3.status_code == 422

    async with async_session_factory() as session:
        from app.models.webhook_event import WebhookEvent

        ev = (await session.exec(select(WebhookEvent).where(WebhookEvent.id == r1.json()["id"]))).first()
        assert ev is not None
