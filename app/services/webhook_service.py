import uuid
from typing import Any, cast

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_factory
from app.core.redis import get_redis
from app.models.audit_log import AuditLog
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.webhook_event import WebhookEvent


class WebhookError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def _log_audit(
    event_type: str,
    user_id: str,
    metadata: dict[str, Any],
    session: AsyncSession | None = None,
) -> None:
    """Log audit event. If session is provided, use it; otherwise use a separate session."""

    async def _do_log(s: AsyncSession) -> None:
        audit = AuditLog(user_id=user_id, event_type=event_type, meta=metadata)
        s.add(audit)
        await s.flush()

    if session is not None:
        await _do_log(session)
    else:
        async with async_session_factory() as audit_session:
            await _do_log(audit_session)
            await audit_session.commit()


async def create_endpoint(
    session: AsyncSession,
    owner_user_id: str,
    url: str,
    secret: str,
    event_types: list[str],
    max_attempts: int,
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
    await _log_audit(
        "webhook_created",
        user_id=owner_user_id,
        metadata={"endpoint_id": endpoint.id, "url": url, "event_types": event_types},
        session=session,
    )
    return endpoint


async def publish_event(
    session: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
    source: str,
    idempotency_key: str | None,
    user_id: str,
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
    # redis-py types rpush as Awaitable[int] | int (sync/async shared mixin);
    # our client from get_redis() is always async, so the cast is sound.
    if created_ids:
        client = get_redis()
        try:
            await cast(Any, client.rpush("webhook:queue", *created_ids))
        except Exception:
            pass

    await _log_audit(
        "webhook_event_published",
        user_id=user_id,
        metadata={
            "event_id": event.id,
            "event_type": event_type,
            "delivery_count": len(created_ids),
        },
        session=session,
    )
    return event, True
