"""Integración contra PostgreSQL/Redis reales. Solo corre en contenedor (db/redis por nombre de servicio)."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.db import async_session_factory
from app.core.security import hash_password
from app.main import app
from app.models.audit_log import AuditLog
from app.models.password_reset_token import PasswordResetToken
from app.models.service_client import ServiceClient


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db() -> None:
    """Clean up test data before each test."""
    async with async_session_factory() as session:
        await session.exec(AuditLog.__table__.delete())
        await session.exec(PasswordResetToken.__table__.delete())
        await session.commit()


def _email() -> str:
    return f"it-{uuid.uuid4().hex[:10]}@test.com"


@pytest.mark.asyncio
async def test_register_login_me_refresh_logout(client: AsyncClient) -> None:
    email = _email()
    r = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecret123"}
    )
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
        session.add(
            ServiceClient(
                client_id=cid, client_secret_hash=hash_password(secret), scopes="webhooks:publish"
            )
        )
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
    tok = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}", "Idempotency-Key": f"it-{uuid.uuid4()}"}

    body = {"type": "user.created", "payload": {"email": email}}
    r1 = await client.post("/api/v1/webhooks/events", json=body, headers=headers)
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/api/v1/webhooks/events", json=body, headers=headers)
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]

    # sin Idempotency-Key -> 422
    r3 = await client.post(
        "/api/v1/webhooks/events", json=body, headers={"Authorization": f"Bearer {tok}"}
    )
    assert r3.status_code == 422

    async with async_session_factory() as session:
        from app.models.webhook_event import WebhookEvent

        ev = (
            await session.exec(select(WebhookEvent).where(WebhookEvent.id == r1.json()["id"]))
        ).first()
        assert ev is not None


@pytest.mark.asyncio
async def test_password_reset_flow(client: AsyncClient) -> None:
    email = _email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    # Login to verify original password works
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    assert r.status_code == 200

    # Request password reset
    r = await client.post("/api/v1/auth/password/reset", json={"email": email})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "reset_token" in data
    reset_token = data["reset_token"]
    assert len(reset_token) > 0

    # Verify audit log for password_reset_requested
    async with async_session_factory() as session:
        audit = (
            await session.exec(
                select(AuditLog).where(AuditLog.event_type == "password_reset_requested")
            )
        ).first()
        assert audit is not None
        assert audit.user_id is not None

    # Confirm password reset with token
    new_password = "newsupersecret456"
    r = await client.post(
        "/api/v1/auth/password/reset/confirm",
        json={"token": reset_token, "new_password": new_password},
    )
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Password has been reset successfully"

    # Verify audit log for password_changed
    async with async_session_factory() as session:
        audit = (
            await session.exec(select(AuditLog).where(AuditLog.event_type == "password_changed"))
        ).first()
        assert audit is not None
        assert audit.meta.get("success") is True

    # Verify new password works
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert r.status_code == 200, r.text
    _ = r.json()["access_token"]

    # Verify old password no longer works
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    assert r.status_code == 401

    # Verify token is now invalid (used)
    r = await client.post(
        "/api/v1/auth/password/reset/confirm",
        json={"token": reset_token, "new_password": "another123"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_password_reset_nonexistent_email(client: AsyncClient) -> None:
    # Should not reveal if email exists
    r = await client.post("/api/v1/auth/password/reset", json={"email": "nonexistent@test.com"})
    assert r.status_code == 200
    assert "If the email exists" in r.json()["message"]


@pytest.mark.asyncio
async def test_audit_logs_on_login_failed(client: AsyncClient) -> None:
    email = _email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})

    # Failed login
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrongpassword"})
    assert r.status_code == 401

    async with async_session_factory() as session:
        audit = (
            await session.exec(select(AuditLog).where(AuditLog.event_type == "login_failed"))
        ).first()
        assert audit is not None
        assert audit.meta.get("reason") == "invalid_credentials"
        assert audit.meta.get("email") == email


@pytest.mark.asyncio
async def test_audit_logs_on_m2m_token(client: AsyncClient) -> None:
    cid = f"tc-{uuid.uuid4().hex[:8]}"
    secret = "tc-secret-1234567890"
    async with async_session_factory() as session:
        session.add(
            ServiceClient(
                client_id=cid, client_secret_hash=hash_password(secret), scopes="webhooks:publish"
            )
        )
        await session.commit()

    r = await client.post("/api/v1/auth/token", json={"client_id": cid, "client_secret": secret})
    assert r.status_code == 200

    async with async_session_factory() as session:
        audit = (
            await session.exec(select(AuditLog).where(AuditLog.event_type == "m2m_token_generated"))
        ).first()
        assert audit is not None
        assert audit.meta.get("success") is True
        assert audit.meta.get("client_id") == cid


@pytest.mark.asyncio
async def test_audit_logs_on_webhook_created(client: AsyncClient) -> None:
    email = _email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": "supersecret123"})
    tok = (
        await client.post("/api/v1/auth/login", json={"email": email, "password": "supersecret123"})
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}

    r = await client.post(
        "/api/v1/webhooks/endpoints",
        json={
            "url": "http://example.com/webhook",
            "secret": "webhook-secret-1234567890",
            "event_types": ["user.created"],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    endpoint_id = r.json()["id"]

    async with async_session_factory() as session:
        audit = (
            await session.exec(select(AuditLog).where(AuditLog.event_type == "webhook_created"))
        ).first()
        assert audit is not None
        assert audit.meta.get("endpoint_id") == endpoint_id
        assert audit.meta.get("url") == "http://example.com/webhook"
