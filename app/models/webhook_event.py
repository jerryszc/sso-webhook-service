import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class WebhookEvent(SQLModel, table=True):
    __tablename__ = "webhook_events"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    type: str = Field(index=True, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    idempotency_key: str = Field(unique=True, index=True, max_length=128)
    source: str = Field(default="internal", max_length=64)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
