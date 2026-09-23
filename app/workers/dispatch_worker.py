import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.redis import get_redis
from app.models.webhook_delivery import WebhookDelivery
from app.models.webhook_endpoint import WebhookEndpoint
from app.models.webhook_event import WebhookEvent
from app.services.dispatcher import next_retry_at, sign_payload

log = logging.getLogger("dispatch_worker")


async def process_delivery(delivery_id: str) -> None:
    async with async_session_factory() as session:
        session_obj: AsyncSession = session
        delivery = (
            await session_obj.exec(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id))
        ).first()
        if delivery is None or delivery.status == "success":
            return
        endpoint = (
            await session_obj.exec(
                select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.endpoint_id)
            )
        ).first()
        event = (
            await session_obj.exec(select(WebhookEvent).where(WebhookEvent.id == delivery.event_id))
        ).first()
        if endpoint is None or event is None or not endpoint.is_active:
            delivery.status = "dlq"
            delivery.error = "Missing endpoint/event or inactive"
            session_obj.add(delivery)
            await session_obj.commit()
            return

        max_attempts = endpoint.max_attempts or settings.webhook_max_attempts
        delivery.attempt += 1
        signature = sign_payload({"type": event.type, "payload": event.payload}, endpoint.secret)
        try:
            async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
                resp = await client.post(
                    endpoint.url,
                    json={"type": event.type, "payload": event.payload},
                    headers={
                        settings.webhook_hmac_header: signature,
                        "X-Event-Type": event.type,
                        "X-Idempotency-Key": event.idempotency_key,
                    },
                )
                delivery.http_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    delivery.status = "success"
                    delivery.error = None
                    delivery.next_retry_at = None
                else:
                    raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:
            delivery.http_status = delivery.http_status
            delivery.error = str(exc)[:2000]
            if delivery.attempt >= max_attempts:
                delivery.status = "dlq"
                delivery.next_retry_at = None
            else:
                delivery.status = "pending"
                delivery.next_retry_at = next_retry_at(delivery.attempt)
                # Requeue with delay via sorted polling: push back after delay
                # redis-py types rpush as Awaitable[int] | int (sync/async shared
                # mixin); our client from get_redis() is always async, so the cast is sound.
                redis = get_redis()
                try:
                    await cast(Any, redis.rpush("webhook:queue", delivery.id))
                except Exception:
                    pass
        delivery.updated_at = datetime.now(UTC)
        session_obj.add(delivery)
        await session_obj.commit()


async def run_forever() -> None:
    redis = get_redis()
    log.warning("dispatch worker started")
    while True:
        try:
            item = await cast(Any, redis.blpop(["webhook:queue"], timeout=5))
        except Exception:
            await asyncio.sleep(2)
            continue
        if not item:
            continue
        _, delivery_id = item
        try:
            await process_delivery(delivery_id)
        except Exception as exc:
            log.exception("delivery failed: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
