import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class WebhookDelivery(SQLModel, table=True):
    __tablename__ = "webhook_deliveries"  # type: ignore[assignment]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    event_id: str = Field(foreign_key="webhook_events.id", index=True)
    endpoint_id: str = Field(foreign_key="webhook_endpoints.id", index=True)
    attempt: int = Field(default=0)
    status: str = Field(default="pending", index=True, max_length=32)
    http_status: int | None = Field(default=None)
    error: str | None = Field(default=None, max_length=2048)
    next_retry_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
