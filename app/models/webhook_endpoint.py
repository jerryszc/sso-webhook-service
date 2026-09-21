import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.user import utcnow


class WebhookEndpoint(SQLModel, table=True):
    __tablename__ = "webhook_endpoints"  # type: ignore[assignment]

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    owner_user_id: str = Field(foreign_key="users.id", index=True)
    url: str = Field(max_length=2048)
    secret: str = Field(max_length=512)
    event_types: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    is_active: bool = Field(default=True)
    max_attempts: int = Field(default=5)
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
