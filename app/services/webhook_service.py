import uuid

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.redis import get_redis
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.webhook_event import WebhookEvent


class WebhookError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def create_endpoint(
    session: AsyncSession, owner_user_id: str, url: str, secret: str, event_types: list[str], max_attempts: int
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        owner_user_id=owner_user_id,
        url=url,
        secret=secret,
        event_types=event_types,
        max_attempts=max_attempts,
    )
    session.add(endpoint)
    await session.flush()
    return endpoint


async def publish_event(
    session: AsyncSession, event_type: str, payload: dict, source: str, idempotency_key: str | None
) -> tuple[WebhookEvent, bool]:
    key = idempotency_key or f"{event_type}:{uuid.uuid4()}"
    existing = (
        await session.exec(select(WebhookEvent).where(WebhookEvent.idempotency_key == key))
    ).first()
    if existing is not None:
        return existing, False

    event = WebhookEvent(type=event_type, payload=payload, idempotency_key=key, source=source)
    session.add(event)
    await session.flush()

    # Fan-out: create pending deliveries for matching active endpoints
    result = await session.exec(select(WebhookEndpoint).where(WebhookEndpoint.is_active == True))  # noqa: E712
    created_ids: list[str] = []
    for endpoint in result.all():
        if event_type in (endpoint.event_types or []):
            delivery = WebhookDelivery(event_id=event.id, endpoint_id=endpoint.id, status="pending")
            session.add(delivery)
            await session.flush()
            created_ids.append(delivery.id)

    # Enqueue delivery ids in Redis
    if created_ids:
        client = get_redis()
        try:
            await client.rpush("webhook:queue", *created_ids)
        except Exception:
            pass
    return event, True
