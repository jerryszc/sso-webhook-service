import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel

from app.core.security import hash_password
from app.main import app
from app.models.service_client import ServiceClient


@pytest_asyncio.fixture
async def client(monkeypatch) -> AsyncClient:
    # Bypass DB/Redis: unit-level contract tests for health + validation
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_validation(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/register", json={"email": "bad", "password": "short"})
    assert r.status_code == 422


def test_password_hash_roundtrip() -> None:
    from app.core.security import verify_password

    h = hash_password("supersecret123")
    assert verify_password("supersecret123", h) is True
    assert verify_password("wrong", h) is False


def test_hmac_signature() -> None:
    from app.services.dispatcher import sign_payload

    s1 = sign_payload({"type": "user.created", "payload": {}}, "secret1234567890")
    s2 = sign_payload({"type": "user.created", "payload": {}}, "secret1234567890")
    assert s1 == s2
    assert len(s1) == 64


def test_backoff_growth() -> None:
    from app.services.dispatcher import compute_backoff

    assert compute_backoff(1).total_seconds() == 2
    assert compute_backoff(2).total_seconds() == 4
    assert compute_backoff(5).total_seconds() == 32
