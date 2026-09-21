from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.audit_log import AuditLog


async def log_audit_event(
    session: AsyncSession,
    event_type: str,
    user_id: str | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    audit = AuditLog(
        user_id=user_id,
        ip=ip,
        event_type=event_type,
        meta=metadata or {},
    )
    session.add(audit)
    await session.flush()
    return audit