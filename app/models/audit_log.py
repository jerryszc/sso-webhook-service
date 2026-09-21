import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"  # type: ignore[assignment]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    ip: str | None = Field(default=None, max_length=45)
    event_type: str = Field(index=True, max_length=64)
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )