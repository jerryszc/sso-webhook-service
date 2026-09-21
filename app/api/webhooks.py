from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_principal
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_endpoint import WebhookEndpoint
from app.schemas.webhooks import (
    DeliveryOut,
    EndpointCreate,
    EndpointOut,
    EventOut,
    EventPublish,
)
from app.services.webhook_service import create_endpoint, publish_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _principal_user_id(principal: dict) -> str:
    if principal["kind"] == "user":
        return principal["user"].id
    return f"client:{principal['client'].client_id}"


def _get_audit_user_id(principal: dict) -> str | None:
    if principal["kind"] == "user":
        return principal["user"].id
    return None


@router.post("/endpoints", response_model=EndpointOut, status_code=status.HTTP_201_CREATED)
async def create_ep(
    body: EndpointCreate,
    principal: dict = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> EndpointOut:
    endpoint = await create_endpoint(
        session, _principal_user_id(principal), str(body.url), body.secret, body.event_types, body.max_attempts
    )
    return EndpointOut(
        id=endpoint.id, url=endpoint.url, event_types=endpoint.event_types,
        is_active=endpoint.is_active, max_attempts=endpoint.max_attempts,
    )


@router.get("/endpoints", response_model=list[EndpointOut])
async def list_eps(
    principal: dict = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[EndpointOut]:
    owner = _principal_user_id(principal)
    result = await session.exec(select(WebhookEndpoint).where(WebhookEndpoint.owner_user_id == owner))
    return [
        EndpointOut(id=e.id, url=e.url, event_types=e.event_types, is_active=e.is_active, max_attempts=e.max_attempts)
        for e in result.all()
    ]


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def publish(
    body: EventPublish,
    principal: dict = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EventOut:
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Idempotency-Key required")
    audit_user_id = _get_audit_user_id(principal)
    if audit_user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User token required for webhook publishing")
    event, _ = await publish_event(session, body.type, body.payload, body.source, idempotency_key, audit_user_id)
    return EventOut(id=event.id, type=event.type, idempotency_key=event.idempotency_key)


@router.get("/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    event_id: str | None = None,
    endpoint_id: str | None = None,
    status_filter: str | None = None,
    principal: dict = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[DeliveryOut]:
    stmt = select(WebhookDelivery)
    if event_id:
        stmt = stmt.where(WebhookDelivery.event_id == event_id)
    if endpoint_id:
        stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)
    if status_filter:
        stmt = stmt.where(WebhookDelivery.status == status_filter)
    result = await session.exec(stmt)
    return [
        DeliveryOut(id=d.id, event_id=d.event_id, endpoint_id=d.endpoint_id, attempt=d.attempt,
                    status=d.status, http_status=d.http_status, error=d.error)
        for d in result.all()
    ]


@router.post("/deliveries/{delivery_id}/retry", response_model=DeliveryOut)
async def retry_delivery(
    delivery_id: str,
    principal: dict = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> DeliveryOut:
    from app.core.redis import get_redis

    delivery = (await session.exec(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id))).first()
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    if delivery.status == "success":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already delivered")
    delivery.status = "pending"
    delivery.next_retry_at = None
    session.add(delivery)
    await session.flush()
    try:
        await get_redis().rpush("webhook:queue", delivery.id)
    except Exception:
        pass
    return DeliveryOut(id=delivery.id, event_id=delivery.event_id, endpoint_id=delivery.endpoint_id,
                       attempt=delivery.attempt, status=delivery.status,
                       http_status=delivery.http_status, error=delivery.error)
